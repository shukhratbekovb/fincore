class TransientDeliveryError(Exception):
    pass


class PermanentDeliveryError(Exception):
    pass


class DeliveryExpiredError(Exception):
    pass
