from components.payments.domain.PaymentError import PaymentError


class TransferNotFoundError(PaymentError):
    code = "TRANSFER_NOT_FOUND"
    http_status = 404
    default_message = "Transfer was not found in this tenant"
