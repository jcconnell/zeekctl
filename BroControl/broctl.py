#! /usr/bin/env python
#
# The BroControl interactive shell.

import os
import sys
import cmd
import time
import platform
import atexit

# Configured by CMake
# Base directory of broctl installation.
BroBase = "@PREFIX@"

# Configured by CMake
# Base directory of bro script files.
BroScriptDir = "@BROSCRIPTDIR@"

# Configured by CMake
# Base directory of broctl configuration files.
BroCfgDir = "@ETC@"

# Configured by CMake
# Version of the broctl distribution.
Version = "@VERSION@"

# Allow user to override default broctl install directory
tmpbrobase = os.getenv("BROCTL_INSTALL_PREFIX")
if tmpbrobase and os.path.isdir(tmpbrobase):
    BroBase = tmpbrobase
    # Note: for now we assume these are subdirectories of BroBase
    tmpbrocfgdir = os.path.join(BroBase, "etc")
    if os.path.isdir(tmpbrocfgdir):
        BroCfgDir = tmpbrocfgdir

    tmpbroscriptdir = os.path.join(BroBase, "share/bro")
    if os.path.isdir(tmpbroscriptdir):
        BroScriptDir = tmpbroscriptdir

# Adjust the PYTHONPATH
sys.path = [os.path.join(BroBase, "lib/broctl")] + sys.path

# We need to add the directory of the Broccoli library files
# to the linker's runtime search path. This is hack which
# restarts the script with the new environment.
ldpath = "LD_LIBRARY_PATH"
if platform.system() == "Darwin":
    ldpath = "DYLD_LIBRARY_PATH"

old = os.environ.get(ldpath)
dir = os.path.join(BroBase, "lib")
if not old or dir not in old:
    if old:
        path = "%s:%s" % (dir, old)
    else:
        path = dir
    os.environ[ldpath] = path
    os.execv(sys.argv[0], sys.argv)

## End of library hack.

# Turns node name arguments into a list of nodes.
def nodeArgs(args):
    if not args:
        args = "all"

    nodes = []

    for arg in args.split():
        h = Config.nodes(arg)
        if not h and arg != "all":
            util.error("unknown node '%s'" % arg)
            return (False, [])

        nodes += h

    return (True, nodes)

# Turns node name arguments into a list of nodes.  The result is a subset of
# a similar call to nodeArgs() but here only one node is chosen for each host.
def nodeHostArgs(args):
    if not args:
        args = "all"

    hosts = {}
    nodes = []

    for arg in args.split():
        h = Config.hosts(arg)
        if not h and arg != "all":
            util.error("unknown node '%s'" % arg)
            return (False, [])

        for node in h:
            if node.host not in hosts:
                hosts[node.host] = 1
                nodes.append(node)

    return (True, nodes)

# Main command loop.
class BroCtlCmdLoop(cmd.Cmd):

    def __init__(self):
        cmd.Cmd.__init__(self)
        self.exit_code = 0
        self._locked = False
        self.prompt = "[BroControl] > "

    def output(self, text):
        self.stdout.write(text)
        self.stdout.write("\n")

    def error(self, str):
        self.output("Error: %s" % str)
        self.exit_code = 1

    def syntax(self, args):
        self.output("Syntax error: %s" % args)
        self.exit_code = 1

    def default(self, line):
        m = line.split()

        cmdout = cmdoutput.CommandOutput()
        if not plugin.Registry.runCustomCommand(m[0], " ".join(m[1:]), cmdout):
            self.error("unknown command '%s'" % m[0])
        cmdout.printResults()

    def emptyline(self):
        pass

    def lock(self):
        cmdout = cmdoutput.CommandOutput()
        lockstatus = util.lock(cmdout)
        cmdout.printResults()
        if not lockstatus:
            sys.exit(1)

        self._locked = True
        statestatus = Config.readState(cmdout)
        cmdout.printResults()
        if not statestatus:
            sys.exit(1)
        config.Config.config["sigint"] = "0"

    def precmd(self, line):
        util.debug(1, line, prefix="command")
        self._locked = False
        self._failed = False
        return line

    def checkForFailure(self, results):
        if control.nodeFailed(results):
            self._failed = True
            self.exit_code = 1

    def failed(self):
        return self._failed

    def postcmd(self, stop, line):
        Config.writeState(cmdout)
        if self._locked:
            util.unlock(cmdout)
            self._locked = False

        execute.clearDeadHostConnections()
        util.debug(1, "done", prefix="command")
        cmdout.printResults()
        return stop

    def do_EOF(self, args):
        return True

    def do_exit(self, args):
        """Terminates the shell."""
        return True

    def do_quit(self, args):
        """Terminates the shell."""
        return True

    def do_nodes(self, args):
        """Prints a list of all configured nodes."""
        if args:
            self.syntax(args)
            return

        self.lock()

        if plugin.Registry.cmdPre("nodes"):
            for n in Config.nodes():
                util.output(n.describe())

        plugin.Registry.cmdPost("nodes")

    def do_config(self, args):
        """Prints all configuration options with their current values."""
        if args:
            self.syntax(args)
            return

        if plugin.Registry.cmdPre("config"):
            for (key, val) in sorted(Config.options()):
                util.output("%s = %s" % (key, val))

        plugin.Registry.cmdPost("config")

    def do_install(self, args):
        """- [--local]

        Reinstalls on all nodes (unless the ``--local`` option is given, in
        which case nothing will be propagated to other nodes), including all
        configuration files and local policy scripts.  Usually all nodes
        should be reinstalled at the same time, as any inconsistencies between
        them will lead to strange effects.  This command must be
        executed after *all* changes to any part of the broctl configuration
        (and after upgrading to a new version of Bro or BroControl),
        otherwise the modifications will not take effect.  Before executing
        ``install``, it is recommended to verify the configuration
        with check_."""

        local = False

        for arg in args.split():
            if arg == "--local":
                local = True
            else:
                self.syntax(args)
                return

        self.lock()

        if plugin.Registry.cmdPre("install"):
            cmdSuccess, cmdOutput = install.install(local)
            if not cmdSuccess:
                self.exit_code = 1
            cmdOutput.printResults()

        plugin.Registry.cmdPost("install")

    def do_start(self, args):
        """- [<nodes>]

        Starts the given nodes, or all nodes if none are specified. Nodes
        already running are left untouched.
        """

        self.lock()
        (success, nodes) = nodeArgs(args)
        if success:
            nodes = plugin.Registry.cmdPreWithNodes("start", nodes)
            results, cmdOutput = control.start(nodes)
            self.checkForFailure(results)
            cmdOutput.printResults()
            plugin.Registry.cmdPostWithResults("start", results)
        else:
            self.exit_code = 1

    def do_stop(self, args):
        """- [<nodes>]

        Stops the given nodes, or all nodes if none are specified. Nodes not
        running are left untouched.
        """
        self.lock()
        (success, nodes) = nodeArgs(args)
        if success:
            nodes = plugin.Registry.cmdPreWithNodes("stop", nodes)
            results, cmdOutput = control.stop(nodes)
            self.checkForFailure(results)
            cmdOutput.printResults()
            plugin.Registry.cmdPostWithResults("stop", results)
        else:
            self.exit_code = 1

    def do_restart(self, args):
        """- [--clean] [<nodes>]

        Restarts the given nodes, or all nodes if none are specified. The
        effect is the same as first executing stop_ followed
        by a start_, giving the same nodes in both cases.
        This command is most useful to activate any changes made to Bro policy
        scripts (after running install_ first). Note that a
        subset of policy changes can also be installed on the fly via
        update_, without requiring a restart.

        If ``--clean`` is given, the installation is reset into a clean state
        before restarting. More precisely, a ``restart --clean`` turns into
        the command sequence stop_, cleanup_, check_, install_, and
        start_.
        """

        clean = False
        try:
            if args.startswith("--clean"):
                args = args[7:]
                clean = True
        except IndexError:
            pass

        (success, nodes) = nodeArgs(args)
        if success:
            nodes = plugin.Registry.cmdPreWithNodes("restart", nodes, clean)
            args = " ".join([ str(n) for n in nodes ])

            util.output("stopping ...")
            self.do_stop(args)
            self.postcmd(False, args) # Need to call manually.

            if self.failed():
                return

            if clean:
                util.output("cleaning up ...")
                self.do_cleanup(args)
                self.postcmd(False, args)

                if self.failed():
                    return

                util.output("checking configurations...")
                self.do_check(args)
                self.postcmd(False, args)

                if self.failed():
                    return

                util.output("installing ...")
                self.do_install("")
                self.postcmd(False, args)

                if self.failed():
                    return

            util.output("starting ...")
            self.do_start(args)
            self.postcmd(False, args)

            plugin.Registry.cmdPostWithNodes("restart", nodes)
        else:
            self.exit_code = 1

    def do_status(self, args):
        """- [<nodes>]

        Prints the current status of the given nodes."""

        self.lock()
        (success, nodes) = nodeArgs(args)
        if success:
            nodes = plugin.Registry.cmdPreWithNodes("status", nodes)
            cmdSuccess, cmdOutput = control.status(nodes)
            if not cmdSuccess:
                self.exit_code = 1
            cmdOutput.printResults()
            plugin.Registry.cmdPostWithNodes("status", nodes)
        else:
            self.exit_code = 1

        return False

    def _do_top_once(self, args):
        cmdout = cmdoutput.CommandOutput()
        lockstatus = util.lock(cmdout)
        if lockstatus:
            # Read state again (may have changed by cron in the meantime).
            if not Config.readState(cmdout):
                cmdout.printResults()
                sys.exit(1)

            (success, nodes) = nodeArgs(args)
            if success:
                nodes = plugin.Registry.cmdPreWithNodes("top", nodes)
                cmdSuccess, cmdOutput = control.top(nodes)
                if not cmdSuccess:
                    self.exit_code = 1
                cmdout.append(cmdOutput)
                plugin.Registry.cmdPostWithNodes("top", nodes)
            else:
                self.exit_code = 1

            util.unlock(cmdout)

        cmdout.printResults()

    def do_top(self, args):
        """- [<nodes>]

        For each of the nodes, prints the status of the two Bro
        processes (parent process and child process) in a *top*-like
        format, including CPU usage and memory consumption. If
        executed interactively, the display is updated frequently
        until key ``q`` is pressed. If invoked non-interactively, the
        status is printed only once."""

        self.lock()

        if not Interactive:
            self._do_top_once(args)
            return

        cmdout = cmdoutput.CommandOutput()
        util.unlock(cmdout)
        cmdout.printResults()

        util.enterCurses()
        util.clearScreen()

        count = 0

        while config.Config.sigint != "1" and util.getCh() != "q":
            if count % 10 == 0:
                util.bufferOutput()
                self._do_top_once(args)
                lines = util.getBufferedOutput()
                util.clearScreen()
                util.printLines(lines)
            time.sleep(.1)
            count += 1

        util.leaveCurses()

        lockstatus = util.lock(cmdout)
        cmdout.printResults()

        if not lockstatus:
            sys.exit(1)

        return False

    def do_diag(self, args):
        """- [<nodes>]

        If a node has terminated unexpectedly, this command prints a (somewhat
        cryptic) summary of its final state including excerpts of any
        stdout/stderr output, resource usage, and also a stack backtrace if a
        core dump is found. The same information is sent out via mail when a
        node is found to have crashed (the "crash report"). While the
        information is mainly intended for debugging, it can also help to find
        misconfigurations (which are usually, but not always, caught by the
        check_ command)."""

        self.lock()
        (success, nodes) = nodeArgs(args)
        if not success:
            self.exit_code = 1
            return

        nodes = plugin.Registry.cmdPreWithNodes("diag", nodes)

        for h in nodes:
            cmdSuccess, cmdOutput = control.crashDiag(h)
            if not cmdSuccess:
                self.exit_code = 1
            cmdOutput.printResults()

        plugin.Registry.cmdPostWithNodes("diag", nodes)

        return False

    def do_attachgdb(self, args):
        """- [<nodes>]

        Primarily for debugging, the command attaches a *gdb* to the main Bro
        process on the given nodes. """

        self.lock()
        (success, nodes) = nodeArgs(args)
        if success:
            nodes = plugin.Registry.cmdPreWithNodes("attachgdb", nodes)
            cmdSuccess, cmdOutput = control.attachGdb(nodes)
            if not cmdSuccess:
                self.exit_code = 1
            cmdOutput.printResults()
            plugin.Registry.cmdPostWithNodes("attachgdb", nodes)
        else:
            self.exit_code = 1

        return False

    def do_cron(self, args):
        """- [enable|disable|?] | [--no-watch]

        This command has two modes of operation. Without arguments (or just
        ``--no-watch``), it performs a set of maintenance tasks, including
        the logging of various statistical information, expiring old log
        files, checking for dead hosts, and restarting nodes which terminated
        unexpectedly (the latter can be suppressed with the ``--no-watch``
        option if no auto-restart is desired). This mode is intended to be
        executed regularly via *cron*, as described in the installation
        instructions. While not intended for interactive use, no harm will be
        caused by executing the command manually: all the maintenance tasks
        will then just be performed one more time.

        The second mode is for interactive usage and determines if the regular
        tasks are indeed performed when ``broctl cron`` is executed. In other
        words, even with ``broctl cron`` in your crontab, you can still
        temporarily disable it by running ``cron disable``, and
        then later reenable with ``cron enable``. This can be helpful while
        working, e.g., on the BroControl configuration and ``cron`` would
        interfere with that. ``cron ?`` can be used to query the current state.
        """

        watch = True

        if args == "--no-watch":
            watch = False

        elif args:
            self.lock()

            if args == "enable":
                if plugin.Registry.cmdPre("cron", args, False):
                    config.Config._setState("cronenabled", "1")
                    util.output("cron enabled")
                plugin.Registry.cmdPost("cron", args, False)

            elif args == "disable":
                if plugin.Registry.cmdPre("cron", args, False):
                    config.Config._setState("cronenabled", "0")
                    util.output("cron disabled")
                plugin.Registry.cmdPost("cron", args, False)

            elif args == "?":
                if plugin.Registry.cmdPre("cron", args, False):
                    util.output("cron " + (config.Config.cronenabled == "0"  and "disabled" or "enabled"))
                plugin.Registry.cmdPost("cron", args, False)

            else:
                util.error("invalid cron argument")
                self.exit_code = 1

            return

        if plugin.Registry.cmdPre("cron", "", watch):
            cmdOutput = cron.doCron(watch)
            cmdOutput.printResults()
        plugin.Registry.cmdPost("cron", "", watch)

        return False

    def do_check(self, args):
        """- [<nodes>]

        Verifies a modified configuration in terms of syntactical correctness
        (most importantly correct syntax in policy scripts). This command
        should be executed for each configuration change *before*
        install_ is used to put the change into place.
        The ``check`` command uses the policy files as found in SitePolicyPath_
        to make sure they compile correctly. If they do, install_
        will then copy them over to an internal place from where the nodes
        will read them at the next start_. This approach
        ensures that new errors in a policy script will not affect currently
        running nodes, even when one or more of them needs to be restarted."""

        self.lock()

        (success, nodes) = nodeArgs(args)

        if success:
            nodes = plugin.Registry.cmdPreWithNodes("check", nodes)
            results, cmdOutput = control.checkConfigs(nodes)
            self.checkForFailure(results)
            cmdOutput.printResults()
            plugin.Registry.cmdPostWithResults("check", results)
        else:
            self.exit_code = 1

        return False

    def do_cleanup(self, args):
        """- [--all] [<nodes>]

        Clears the nodes' spool directories (if they are not running
        currently). This implies that their persistent state is flushed. Nodes
        that were crashed are reset into *stopped* state. If ``--all`` is
        specified, this command also removes the content of the node's
        TmpDir_, in particular deleteing any data
        potentially saved there for reference from previous crashes.
        Generally, if you want to reset the installation back into a clean
        state, you can first stop_ all nodes, then execute
        ``cleanup --all``, and finally start_ all nodes
        again."""

        cleantmp = False
        try:
            if args.startswith("--all"):
                args = args[5:]
                cleantmp = True
        except IndexError:
            pass

        self.lock()
        (success, nodes) = nodeArgs(args)
        if not success:
            self.exit_code = 1
            return

        nodes = plugin.Registry.cmdPreWithNodes("cleanup", nodes, cleantmp)
        cmdSuccess, cmdOutput = control.cleanup(nodes, cleantmp)
        if not cmdSuccess:
            self.exit_code = 1
        cmdOutput.printResults()
        plugin.Registry.cmdPostWithNodes("cleanup", nodes, cleantmp)

        return False

    def do_capstats(self, args):
        """- [<nodes>] [<interval>]

        Determines the current load on the network interfaces monitored by
        each of the given worker nodes. The load is measured over the
        specified interval (in seconds), or by default over 10 seconds. This
        command uses the :doc:`capstats<../../components/capstats/README>`
        tool, which is installed along with ``broctl``.

        (Note: When using a CFlow and the CFlow command line utility is
        installed as well, the ``capstats`` command can also query the device
        for port statistics. *TODO*: document how to set this up.)"""

        interval = 10
        args = args.split()

        try:
            interval = max(1, int(args[-1]))
            args = args[0:-1]
        except ValueError:
            pass
        except IndexError:
            pass

        args = " ".join(args)

        self.lock()
        (success, nodes) = nodeArgs(args)
        if success:
            nodes = plugin.Registry.cmdPreWithNodes("capstats", nodes, interval)
            cmdSuccess, cmdOutput_cap, cmdOutput_cflow = control.capstats(nodes, interval)
            if not cmdSuccess:
                self.exit_code = 1
            cmdOutput_cap.printResults()
            cmdOutput_cflow.printResults()
            plugin.Registry.cmdPostWithNodes("capstats", nodes, interval)
        else:
            self.exit_code = 1

        return False

    def do_update(self, args):
        """- [<nodes>]

        After a change to Bro policy scripts, this command updates the Bro
        processes on the given nodes *while they are running* (i.e., without
        requiring a restart_). However, such dynamic
        updates work only for a *subset* of Bro's full configuration. The
        following changes can be applied on the fly:  The value of all
        const variables defined with the ``&redef`` attribute can be changed.
        More extensive script changes are not possible during runtime and
        always require a restart; if you change more than just the values of
        ``&redef``-able consts and still issue ``update``, the results are
        undefined and can lead to crashes. Also note that before running
        ``update``, you still need to do an install_ (preferably after
        check_), as otherwise ``update`` will not see the changes and it will
        resend the old configuration."""

        self.lock()
        (success, nodes) = nodeArgs(args)
        if success:
            nodes = plugin.Registry.cmdPreWithNodes("update", nodes)
            results, cmdOutput = control.update(nodes)
            self.checkForFailure(results)
            cmdOutput.printResults()
            plugin.Registry.cmdPostWithResults("update", results)
        else:
            self.exit_code = 1

        return False

    def do_df(self, args):
        """- [<nodes>]

        Reports the amount of disk space available on the nodes. Shows only
        paths relevant to the broctl installation."""

        self.lock()
        (success, nodes) = nodeHostArgs(args)
        if success:
            nodes = plugin.Registry.cmdPreWithNodes("df", nodes)
            cmdSuccess, cmdOutput = control.df(nodes)
            if not cmdSuccess:
                self.exit_code = 1
            cmdOutput.printResults()
            plugin.Registry.cmdPostWithNodes("df", nodes)
        else:
            self.exit_code = 1

        return False

    def do_print(self, args):
        """- <id> [<nodes>]

        Reports the *current* live value of the given Bro script ID on all of
        the specified nodes (which obviously must be running). This can for
        example be useful to (1) check that policy scripts are working as
        expected, or (2) confirm that configuration changes have in fact been
        applied.  Note that IDs defined inside a Bro namespace must be
        prefixed with ``<namespace>::`` (e.g.,
        ``print HTTP::mime_types_extensions`` to print the corresponding
        table from ``file-ident.bro``)."""

        self.lock()
        args = args.split()
        try:
            id = args[0]

            (success, nodes) = nodeArgs(" ".join(args[1:]))
            if success:
                nodes = plugin.Registry.cmdPreWithNodes("print", nodes, id)
                cmdSuccess, cmdOutput = control.printID(nodes, id)
                if not cmdSuccess:
                    self.exit_code = 1
                cmdOutput.printResults()
                plugin.Registry.cmdPostWithNodes("print", nodes, id)
            else:
                self.exit_code = 1
        except IndexError:
            self.syntax("no id given to print")

        return False

    def do_peerstatus(self, args):
        """- [<nodes>]

		Primarily for debugging, ``peerstatus`` reports statistics about the
        network connections cluster nodes are using to communicate with other
        nodes."""

        self.lock()
        (success, nodes) = nodeArgs(args)
        if success:
            nodes = plugin.Registry.cmdPreWithNodes("peerstatus", nodes)
            cmdSuccess, cmdOutput = control.peerStatus(nodes)
            if not cmdSuccess:
                self.exit_code = 1
            cmdOutput.printResults()
            plugin.Registry.cmdPostWithNodes("peerstatus", nodes)
        else:
            self.exit_code = 1

        return False

    def do_netstats(self, args):
        """- [<nodes>]

		Queries each of the nodes for their current counts of captured and
        dropped packets."""

        if not args:
            if config.Config.nodes("standalone"):
                args = "standalone"
            else:
                args = "workers"

        self.lock()
        (success, nodes) = nodeArgs(args)
        if success:
            nodes = plugin.Registry.cmdPreWithNodes("netstats", nodes)
            cmdSuccess, cmdOutput = control.netStats(nodes)
            if not cmdSuccess:
                self.exit_code = 1
            cmdOutput.printResults()
            plugin.Registry.cmdPostWithNodes("netstats", nodes)
        else:
            self.exit_code = 1

        return False

    def do_exec(self, args):
        """- <command line>

		Executes the given Unix shell command line on all hosts configured to
        run at least one Bro instance. This is handy to quickly perform an
        action across all systems."""

        self.lock()
        if plugin.Registry.cmdPre("exec", args):
            cmdSuccess, cmdOutput = control.executeCmd(Config.hosts(), args)
            if not cmdSuccess:
                self.exit_code = 1
            cmdOutput.printResults()
        plugin.Registry.cmdPost("exec", args)

        return False

    def do_scripts(self, args):
        """- [-c] [<nodes>]

		Primarily for debugging Bro configurations, the ``scripts``
       	command lists all the Bro scripts loaded by each of the nodes in the
        order they will be parsed by the node at startup.
        If ``-c`` is given, the command operates as check_ does: it reads
        the policy files from their *original* location, not the copies
        installed by install_. The latter option is useful to check a
        not yet installed configuration."""

        check = False

        args = args.split()

        try:
            while args[0].startswith("-"):

                opt = args[0]

                if opt == "-c":
                    # Check non-installed policies.
                    check = True
                else:
                    self.syntax("unknown option %s" % args[0])
                    return

                args = args[1:]

        except IndexError:
            pass

        args = " ".join(args)

        self.lock()

        (success, nodes) = nodeArgs(args)

        if success:
            nodes = plugin.Registry.cmdPreWithNodes("scripts", nodes, check)
            results, cmdOutput = control.listScripts(nodes, check)
            self.checkForFailure(results)
            cmdOutput.printResults()
            plugin.Registry.cmdPostWithNodes("scripts", nodes, check)
        else:
            self.exit_code = 1

        return False

    def do_process(self, args):
        """- <trace> [options] [-- <scripts>]

        Runs Bro offline on a given trace file using the same configuration as
        when running live. It does, however, use the potentially
        not-yet-installed policy files in SitePolicyPath_ and disables log
        rotation. Additional Bro command line flags and scripts can
        be given (each argument after a ``--`` argument is interpreted as
        a script).

        Upon completion, the command prints a path where the log files can be
        found. Subsequent runs of this command may delete these logs.

        In cluster mode, Bro is run with *both* manager and worker scripts
        loaded into a single instance. While that doesn't fully reproduce the
        live setup, it is often sufficient for debugging analysis scripts.
        """
        options = []
        scripts = []
        trace = None
        in_scripts = False
        cmdSuccess = False

        for arg in args.split():

            if not trace:
                trace = arg
                continue

            if arg == "--":
                if in_scripts:
                    self.syntax("cannot parse arguments")
                    return

                in_scripts = True
                continue

            if not in_scripts:
                options += [arg]

            else:
                scripts += [arg]

        if not trace:
            self.syntax("no trace file given")
            return

        if plugin.Registry.cmdPre("process", trace, options, scripts):
            cmdSuccess, cmdOutput = control.processTrace(trace, options, scripts)
            cmdOutput.printResults()
        plugin.Registry.cmdPost("process", trace, options, scripts, cmdSuccess)

        if not cmdSuccess:
            self.exit_code = 1

    def completedefault(self, text, line, begidx, endidx):
        # Commands that take a "<nodes>" argument.
        nodes_cmds = ["capstats", "check", "cleanup", "df", "diag", "netstats", "print", "restart", "start", "status", "stop", "top", "update", "attachgdb", "peerstatus", "scripts"]

        args = line.split()

        if not args or args[0] not in nodes_cmds:
            return []

        nodes = ["manager", "workers", "proxies", "all"] + [n.name for n in Config.nodes()]

        return [n for n in nodes if n.startswith(text)]

    # Prints the command's docstring in a form suitable for direct inclusion
    # into the documentation.
    def printReference(self):
        print ".. Automatically generated. Do not edit."
        print

        cmds = []

        for i in self.__class__.__dict__:
            doc = self.__class__.__dict__[i].__doc__
            if i.startswith("do_") and doc:
                cmds += [(i[3:], doc)]

        cmds.sort()

        for (cmd, doc) in cmds:
            if doc.startswith("- "):
                # First line are arguments.
                doc = doc.split("\n")
                args = doc[0][2:]
                doc = "\n".join(doc[1:])
            else:
                args = ""

            if args:
                args = (" *%s*" % args)
            else:
                args = ""

            output = ""
            for line in doc.split("\n"):
                line = line.strip()
                output += "    " + line + "\n"

            output = output.strip()

            print
            print ".. _%s:\n\n*%s*%s\n    %s" % (cmd, cmd, args, output)
            print

    def do_help(self, args):
        """Prints a brief summary of all commands understood by the shell."""

        plugin_help = ""

        for (cmd, args, descr) in plugin.Registry.allCustomCommands():
            if not plugin_help:
                plugin_help += "\nCommands provided by plugins:\n\n"

            if args:
                cmd = "%s %s" % (cmd, args)

            plugin_help += "  %-32s - %s\n" % (cmd, descr)

        self.output(
"""
BroControl Version %s

  capstats [<nodes>] [<secs>]      - Report interface statistics with capstats
  check [<nodes>]                  - Check configuration before installing it
  cleanup [--all] [<nodes>]        - Delete working dirs (flush state) on nodes
  config                           - Print broctl configuration
  cron [--no-watch]                - Perform jobs intended to run from cron
  cron enable|disable|?            - Enable/disable \"cron\" jobs
  df [<nodes>]                     - Print nodes' current disk usage
  diag [<nodes>]                   - Output diagnostics for nodes
  exec <shell cmd>                 - Execute shell command on all hosts
  exit                             - Exit shell
  install                          - Update broctl installation/configuration
  netstats [<nodes>]               - Print nodes' current packet counters
  nodes                            - Print node configuration
  peerstatus [<nodes>]             - Print status of nodes' remote connections
  print <id> [<nodes>]             - Print values of script variable at nodes
  process <trace> [<op>] [-- <sc>] - Run Bro (with options and scripts) on trace
  quit                             - Exit shell
  restart [--clean] [<nodes>]      - Stop and then restart processing
  scripts [-c] [<nodes>]           - List the Bro scripts the nodes will load
  start [<nodes>]                  - Start processing
  status [<nodes>]                 - Summarize node status
  stop [<nodes>]                   - Stop processing
  top [<nodes>]                    - Show Bro processes ala top
  update [<nodes>]                 - Update configuration of nodes on the fly
  %s""" % (Version, plugin_help))

# Hidden command to print the command documentation.
if len(sys.argv) == 2 and sys.argv[1] == "--print-doc":
    loop = BroCtlCmdLoop()
    loop.printReference()
    sys.exit(loop.exit_code)

# Here so that we don't need the PYTHONPATH to be setup for --print-doc.
from BroControl import util
from BroControl import cmdoutput
from BroControl import config
from BroControl import execute
from BroControl import install
from BroControl import control
from BroControl import cron
from BroControl import plugin
from BroControl.config import Config


def saveState(loop):
    global cmdout
    # If we're still locked, we might have unsaved changed.
    if loop._locked:
        print >>sys.stderr, "abnormal termination, saving state ..."
        Config.writeState(cmdout)
        cmdout.printResults()

cmdout = cmdoutput.CommandOutput()
try:
    Config = config.Configuration(os.path.join(BroCfgDir, "broctl.cfg"), BroBase, BroScriptDir, Version, cmdout)
except RuntimeError:
    cmdout.printResults()
    sys.exit(1)

cmdout.printResults()

for dir in Config.sitepluginpath.split(":") + [Config.plugindir]:
    if dir:
        plugin.Registry.addDir(dir)

if not plugin.Registry.loadPlugins(cmdout):
    cmdout.printResults()
    sys.exit(1)
if not Config.initPostPlugins(cmdout):
    cmdout.printResults()
    sys.exit(1)
    
plugin.Registry.initPlugins()

util.enableSignals()

loop = BroCtlCmdLoop()

atexit.register(saveState, loop)

try:
    os.chdir(Config.brobase)
except:
    pass

if not config.Config.warnBroctlInstall(cmdout):
    cmdout.printResults()
    sys.exit(1)

cmdout.printResults()

if len(sys.argv) > 1:
    Interactive = False
    line = " ".join(sys.argv[1:])
    loop.precmd(line)
    loop.onecmd(line)
    loop.postcmd(False, line)
else:
    Interactive = True
    loop.cmdloop("\nWelcome to BroControl %s\n\nType \"help\" for help.\n" % Version)

plugin.Registry.finishPlugins()
sys.exit(loop.exit_code)