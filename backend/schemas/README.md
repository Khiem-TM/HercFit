# Backend schemas

Schemas import without SQLAlchemy, settings, API keys or a database connection.
They are the single place for input types, lengths, ranges, timezone requirements,
JSON structure and cross-field rules. Shared enums remain importable from the
existing model modules, but their definitions live in `schemas.enums`.

| Model | Input contracts | Output |
| --- | --- | --- |
| User | `UserCreate`, `UserUpdate`, `OnboardingInput`, `GoogleProfile` | `UserRead` |
| BodyMetric | `BodyMetricCreate` / `BodyMetricReplace`, `BodyMetricQuery` | `BodyMetricRead` |
| FoodItem | `FoodCreate`, `SystemFoodCreate`, `FoodUpdate`, `FoodQuery` | `FoodRead` |
| Goal | `GoalCreate`, `GoalUpdate`, `GoalUpdateRequest` | `GoalRead` |
| OAuthAccount | `OAuthAccountCreate`, `OAuthTokenUpdate` | `OAuthAccountRead` |
| AuthSession | `AuthSessionCreate`, `AuthSessionRevoke` | `AuthSessionRead` |

Use scoped model methods for backend business operations. They accept a mapping
or the corresponding schema and delegate validation to Pydantic before writing:

```python
payload = GoalCreate.model_validate(request_data)
goal = await Goal.create_for_user(session, user_id=current_user.id, payload=payload)
response = GoalRead.model_validate(goal)

patch = GoalUpdateRequest.model_validate(request_patch)
goal = await Goal.update_for_user(
    session, goal_id, user_id=current_user.id,
    payload=patch.to_payload(), expected_version_id=patch.expected_version_id,
)
```

`to_payload()` preserves `Decimal`, UUID and date/time values for SQLAlchemy.
It excludes omitted fields, including nested fields, but keeps explicitly supplied
null values for nullable columns. PATCH JSON fields replace the supplied object;
`User.update_personal_info` is the explicit top-level merge operation.
`Goal.update_for_user` validates a partial date change against the stored dates.

Input schemas forbid unknown fields, including identity/ownership and lifecycle
fields in user-facing payloads. OAuth provider responses alone ignore unknown
claims. OAuth token schemas are internal: secrets are masked in repr/JSON, while
`OAuthAccountCreate.to_payload()` unwraps them only for storage. Never return an
input payload as an API response. Read schemas exclude token material.

The model layer retains database constraints, ownership checks, lifecycle rules,
snapshot immutability, row locks, optimistic version checks and transaction logic.
Generic inherited `BaseModel` CRUD is trusted internal persistence; it does not
automatically choose a domain schema. Raw ORM assignment bypasses input validation
and still obeys database constraints and business-invariant hooks.

Install `backend/requirements.txt` (includes `pydantic[email]`). Run offline schema
tests with `PYTHONPATH=backend python -m unittest discover -s backend/tests -p test_schemas.py`.
