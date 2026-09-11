# Development scripts

Canonical commands live in the root pyproject and package.json. Add cross-platform
helper scripts here only when needed.

`validate_contribution.py` is the single executable policy for commit messages,
branch names, and pull-request titles. Local Git hooks and GitHub Actions invoke
the same implementation so their behavior cannot drift. Keep it standard-library
only and update its unit tests with every policy change.
