import os
import logging
import time
from dataclasses import dataclass
from typing import Protocol

import requests
from django.conf import settings
from pymesomb import __version__
from pymesomb.operations import PaymentOperation


logger = logging.getLogger("pivot.payments")


def _masked_phone(value):
    value = str(value or "")
    return f"***{value[-4:]}" if value else "<vide>"


class TimeoutPaymentOperation(PaymentOperation):
    """PaymentOperation avec délais explicites, absents du SDK PyMeSomb."""

    def execute_request(self, method, endpoint, date, nonce="", body=None, mode=None):
        url = self.build_url(endpoint)
        headers = {
            "x-mesomb-date": str(int(date.timestamp())),
            "x-mesomb-nonce": nonce,
            "Accept-Language": self.language,
            "X-MeSomb-Source": f"PyMeSomb/{__version__}",
            "X-MeSomb-Application": self.target,
        }
        request_body = dict(body) if body else None
        if request_body and "trxID" in request_body:
            headers["X-MeSomb-TrxID"] = str(request_body.pop("trxID"))
        if mode:
            headers["X-MeSomb-OperationMode"] = mode
        if method == "POST":
            authorization = self.get_authorization(
                method,
                endpoint,
                date,
                nonce,
                headers={"content-type": "application/json"},
                body=request_body,
            )
        else:
            authorization = self.get_authorization(method, endpoint, date, nonce)
        headers["Authorization"] = authorization
        session = requests.Session()
        session.trust_env = settings.MESOMB_USE_SYSTEM_PROXY
        response = session.request(
            method, url, json=request_body, headers=headers,
            timeout=(settings.MESOMB_CONNECT_TIMEOUT, settings.MESOMB_READ_TIMEOUT),
        )
        if response.status_code >= 400:
            self.process_client_exception(response)
        try:
            data = response.json()
            self.last_response_data = data
            return data
        except ValueError:
            self.last_response_data = {}
            return {}


def map_provider_status(provider_status):
    value = str(provider_status or "UNKNOWN").upper()
    if value in {"SUCCESS", "SUCCEEDED", "COMPLETED"}:
        return "success", value
    if value in {"CANCELLED", "CANCELED"}:
        return "cancelled", value
    if value in {"FAILED", "FAIL", "FAILURE", "REJECTED", "DECLINED", "DENIED"}:
        return "failed", value
    if value in {"EXPIRED", "TIMEOUT", "TIMED_OUT"}:
        return "expired", value
    return "pending", value


@dataclass(frozen=True)
class GatewayResult:
    status: str
    reference: str = ""
    redacted: dict | None = None
    operator_reference: str = ""


class PaymentGateway(Protocol):
    def collect(self, *, amount, operator, phone, reference) -> GatewayResult: ...

    def query(self, *, reference, source="MESOMB") -> GatewayResult: ...


class FakePaymentGateway:
    provider = "simulated"

    def __init__(self, status="success"):
        self.status = status

    def collect(self, **kwargs):
        return GatewayResult(self.status, f"SIM-{kwargs['reference']}", {"simulated": True}, f"OP-{kwargs['reference']}")

    def query(self, *, reference, source="MESOMB"):
        return GatewayResult(self.status, reference, {"simulated": True})


class MeSombGateway:
    provider = "mesomb"

    def __init__(self):
        self.application_key = (
            os.environ.get("MESOMB_APPLICATION_KEY")
            or os.environ.get("MESOMB_APP_KEY")
            or settings.MESOMB_APPLICATION_KEY
        )
        self.access_key = os.environ.get("MESOMB_ACCESS_KEY") or settings.MESOMB_ACCESS_KEY
        self.secret_key = os.environ.get("MESOMB_SECRET_KEY") or settings.MESOMB_SECRET_KEY
        self.country = os.environ.get("MESOMB_COUNTRY") or settings.MESOMB_COUNTRY
        self.currency = os.environ.get("MESOMB_CURRENCY") or settings.MESOMB_CURRENCY

    def _operation(self):
        return TimeoutPaymentOperation(self.application_key, self.access_key, self.secret_key)

    def _retry_query(self, callback):
        attempts = max(settings.MESOMB_MAX_RETRIES, 0) + 1
        for attempt in range(attempts):
            try:
                return callback()
            except requests.RequestException:
                if attempt == attempts - 1:
                    raise
                time.sleep(settings.MESOMB_RETRY_BACKOFF * (2**attempt))

    def collect(self, **kwargs):
        if not all((self.application_key, self.access_key, self.secret_key)):
            raise RuntimeError("Configuration MeSomb absente")
        # Une collecte n'est retentée que sur ConnectTimeout : après un ReadTimeout,
        # MeSomb peut déjà avoir débité le client et le rapprochement doit prendre le relais.
        operation = self._operation()
        collect_params = dict(
            payer=kwargs["phone"],
            amount=int(kwargs["amount"]),
            service=kwargs["operator"].upper(),
            country=self.country,
            currency=self.currency,
            trx_id=kwargs["reference"],
            mode=settings.MESOMB_OPERATION_MODE,
        )
        logger.info(
            "MESOMB COLLECT start reference=%s amount=%s currency=%s operator=%s payer=%s country=%s mode=%s",
            kwargs["reference"], kwargs["amount"], self.currency, kwargs["operator"].upper(),
            _masked_phone(kwargs["phone"]), self.country, settings.MESOMB_OPERATION_MODE,
        )
        attempts = max(settings.MESOMB_MAX_RETRIES, 0) + 1
        for attempt in range(attempts):
            try:
                response = operation.make_collect(**collect_params)
                break
            except TypeError:
                raw = getattr(operation, "last_response_data", None)
                if not isinstance(raw, dict) or raw.get("transaction") is not None:
                    raise
                raw_success = raw.get("success")
                raw_status = str(raw.get("status") or ("PENDING" if raw_success else "FAILED")).upper()
                status, provider_status = map_provider_status(raw_status)
                logger.warning(
                    "MESOMB COLLECT asynchronous-empty-transaction reference=%s provider_status=%s success=%s",
                    kwargs["reference"], provider_status, raw_success,
                )
                return GatewayResult(
                    status,
                    str(raw.get("reference") or kwargs["reference"]),
                    {
                        "provider": "mesomb",
                        "status": provider_status,
                        "success": raw_success,
                        "code": raw.get("code"),
                    },
                    str(raw.get("transaction") or raw.get("operator_reference") or ""),
                )
            except requests.ConnectTimeout:
                logger.warning(
                    "MESOMB COLLECT connect-timeout reference=%s attempt=%s/%s",
                    kwargs["reference"], attempt + 1, attempts,
                )
                if attempt == attempts - 1:
                    raise
                time.sleep(settings.MESOMB_RETRY_BACKOFF * (2**attempt))
        status, provider_status = map_provider_status(response.transaction.status)
        if response.is_transaction_success():
            status = "success"
        logger.info(
            "MESOMB COLLECT response reference=%s provider_reference=%s provider_status=%s mapped_status=%s",
            kwargs["reference"], response.reference or getattr(response.transaction, "pk", ""),
            provider_status, status,
        )
        return GatewayResult(
            status,
            response.reference
            or getattr(response.transaction, "pk", "")
            or kwargs["reference"],
            {"provider": "mesomb", "status": provider_status},
            str(getattr(response.transaction, "pk", "") or ""),
        )

    def query(self, *, reference, source="MESOMB"):
        if not all((self.application_key, self.access_key, self.secret_key)):
            raise RuntimeError("Configuration MeSomb absente")
        operation = self._operation()
        logger.info("MESOMB QUERY start reference=%s source=%s", reference, source)
        transactions = self._retry_query(
            lambda: operation.check_transactions([reference], source=source)
        )
        if not transactions:
            logger.warning("MESOMB QUERY empty reference=%s source=%s", reference, source)
            return GatewayResult("pending", reference, {"provider": "mesomb", "status": "UNKNOWN"})
        transaction = transactions[0]
        status, provider_status = map_provider_status(transaction.status)
        logger.info(
            "MESOMB QUERY response reference=%s provider_status=%s mapped_status=%s",
            reference, provider_status, status,
        )
        return GatewayResult(
            status,
            getattr(transaction, "pk", None) or reference,
            {"provider": "mesomb", "status": provider_status},
            str(getattr(transaction, "reference", None) or ""),
        )


def configured_gateway():
    gateway_name = os.environ.get("PAYMENT_GATEWAY", settings.PAYMENT_GATEWAY).strip().lower()
    if gateway_name == "mesomb":
        return MeSombGateway()
    if gateway_name == "simulated":
        return FakePaymentGateway()
    raise RuntimeError(f"Fournisseur de paiement inconnu : {gateway_name}")
