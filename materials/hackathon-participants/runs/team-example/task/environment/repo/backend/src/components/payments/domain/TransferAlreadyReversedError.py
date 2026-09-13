from components.payments.domain.PaymentError import PaymentError


class TransferAlreadyReversedError(PaymentError):
    code = "TRANSFER_ALREADY_REVERSED"
    http_status = 409
    default_message = "Transfer has already been reversed"
