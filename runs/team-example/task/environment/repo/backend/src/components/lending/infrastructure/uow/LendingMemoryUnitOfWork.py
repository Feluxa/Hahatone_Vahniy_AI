from collections.abc import Mapping

from pydantic import BaseModel

from system.uow.IUnitOfWork import IUnitOfWork


class LendingMemoryUnitOfWork(IUnitOfWork):
    """A tiny transaction boundary for the single-process reference adapter."""

    def __init__(self, store: dict[str, dict[tuple[str, ...], BaseModel]]) -> None:
        self._store = store
        self._new: list[BaseModel] = []
        self._dirty: list[BaseModel] = []
        self._deleted: list[BaseModel] = []
        self.commits = 0
        self.rollbacks = 0

    def register_new(self, model: BaseModel) -> None:
        self._new.append(model)

    def register_dirty(self, model: BaseModel) -> None:
        self._dirty.append(model)

    def register_deleted(self, model: BaseModel) -> None:
        self._deleted.append(model)

    async def commit(self) -> None:
        candidate = self._clone_store()
        self._validate_and_apply(candidate)
        self._store.clear()
        self._store.update(candidate)
        self._new.clear()
        self._dirty.clear()
        self._deleted.clear()
        self.commits += 1

    async def rollback(self) -> None:
        self._new.clear()
        self._dirty.clear()
        self._deleted.clear()
        self.rollbacks += 1

    def snapshot(self) -> Mapping[str, Mapping[tuple[str, ...], BaseModel]]:
        return {name: dict(items) for name, items in self._store.items()}

    def _clone_store(self) -> dict[str, dict[tuple[str, ...], BaseModel]]:
        return {
            bucket: {key: model.model_copy(deep=True) for key, model in records.items()}
            for bucket, records in self._store.items()
        }

    def _validate_and_apply(self, candidate: dict[str, dict[tuple[str, ...], BaseModel]]) -> None:
        locations = [(self._location(model), model) for model in self._new]
        locations.extend((self._location(model), model) for model in self._dirty)
        locations.extend((self._location(model), model) for model in self._deleted)
        seen_new: set[tuple[str, tuple[str, ...]]] = set()
        for (bucket, key), _ in locations[: len(self._new)]:
            if (bucket, key) in seen_new or key in candidate.get(bucket, {}):
                raise ValueError(f"duplicate lending record {bucket}:{key}")
            seen_new.add((bucket, key))
        for (bucket, key), _ in locations[len(self._new) : len(self._new) + len(self._dirty)]:
            if key not in candidate.get(bucket, {}):
                raise ValueError(f"cannot update missing lending record {bucket}:{key}")
        for (bucket, key), _ in locations[len(self._new) + len(self._dirty) :]:
            if key not in candidate.get(bucket, {}):
                raise ValueError(f"cannot delete missing lending record {bucket}:{key}")
        for (_, _), model in locations[: len(self._new)]:
            self._write(candidate, model)
        for (_, _), model in locations[len(self._new) : len(self._new) + len(self._dirty)]:
            self._write(candidate, model)
        for (bucket, key), _ in locations[len(self._new) + len(self._dirty) :]:
            candidate[bucket].pop(key)

    def _write(self, store: dict[str, dict[tuple[str, ...], BaseModel]], model: BaseModel) -> None:
        bucket, key = self._location(model)
        store.setdefault(bucket, {})[key] = model.model_copy(deep=True)

    def _location(self, model: BaseModel) -> tuple[str, tuple[str, ...]]:
        fields = model.model_dump()
        if "balance" in fields and "loan_id" in fields:
            return "early_funds", (fields["tenant_id"], fields["loan_id"])
        if "installment_no" in fields:
            return "installments", (fields["tenant_id"], fields["loan_id"], str(fields["installment_no"]))
        if "payment_id" in fields:
            return "payments", (fields["tenant_id"], fields["loan_id"], fields["payment_id"])
        if "loan_id" in fields:
            return "loans", (fields["tenant_id"], fields["loan_id"])
        raise ValueError(f"unsupported lending model {model.__class__.__name__}")
