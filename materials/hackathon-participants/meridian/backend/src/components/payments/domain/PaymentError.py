from common.errors.AppError import AppError


class PaymentError(AppError):
    code = "PAYMENT_ERROR"
    http_status = 400
    default_message = "Payment request could not be processed"
