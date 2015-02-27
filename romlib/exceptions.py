class SpecFieldMismatch(Exception):

    def __init__(self, message, required, provided):
        super().__init__(message)
        self.message = message
        self.required = required
        self.provided = provided

    def __str__(self):
        reqstr = "Fields required: {}".format(self.required)
        provstr = "Fields provided: {}".format(self.provided)
        return "\n".join([self.message, reqstr, provstr])

class RomMapError(Exception):
    pass
