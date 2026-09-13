from components.payments.domain.PaymentError import PaymentError


class IdempotencyConflictError(PaymentError):
    code = "IDEMPOTENCY_CONFLICT"
    http_status = 409
    default_message = "Idempotency key was already used for a different request"
