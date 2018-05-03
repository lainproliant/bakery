#--------------------------------------------------------------------
class BuildError(Exception):
    pass

#--------------------------------------------------------------------
class TargetConflictError(BuildError):
    def __init__(self, message, targets):
        super().__init__('%s. (%s)' % (message, ', '.join(targets)))

#--------------------------------------------------------------------
class JobError(BuildError):
    pass

#--------------------------------------------------------------------
class SubprocessError(JobError):
    def __init__(self, cmd_line, output, err_output, returncode):
        super().__init__('Failed to execute command: %s' % ' '.join(cmd_line))
        self.cmd_line = cmd_line
        self.output = output
        self.err_output = err_output
        self.returncode = returncode

#--------------------------------------------------------------------
class EvaluationError(BuildError):
    pass

#--------------------------------------------------------------------
class InternalError(Exception):
    pass

