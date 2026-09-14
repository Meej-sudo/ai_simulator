class ServiceError(Exception):
    pass


class NotFoundError(ServiceError):
    pass


class InvalidOperationError(ServiceError):
    pass
