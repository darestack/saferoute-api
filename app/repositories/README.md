# Repository Layer

This package provides a repository abstraction over Supabase data access.

## Usage

```python
from app.repositories import route_repository

route = await route_repository.find_active_by_slug("my-slug")
```

## Migrating Route Modules

To migrate a route module to use the repository:

1. Replace direct `admin.table(...).execute()` calls with repository methods
2. Replace `get_owned_route_or_404()` with `route_repository.find_by_id()`
3. Update tests to mock the repository instead of `admin`

## Benefits

- **Testability**: Easy to mock repository in tests
- **Swappability**: Can replace Supabase with another backend
- **Consistency**: Centralized query logic and error handling
