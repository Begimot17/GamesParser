# TODO

## General
- [x] Create a unified project management guide (`PROJECT_MANAGEMENT.md`)

## Refactoring
- [x] Refactor the `pikabu_parser.py` for better readability and maintainability.
- [x] Refactor the other parsers (`vgtimes_parser.py`, `stopgame_parser.py`).
- [x] Simplify the project structure.

## Testing
- [x] Create initial unit tests for all parsers.
- [x] Write comprehensive unit tests for `pikabu_parser.py`.
- [x] Write comprehensive unit tests for `vgtimes_parser.py`.
- [x] Write comprehensive unit tests for `stopgame_parser.py`.
- [x] Add integration tests for the parsing process.
- [x] Write tests for new features (LLM provider and validator).

## Logging and Error Handling
- [x] Implement saving of warning logs to a separate file.
- [x] Implement saving of HTML content for pages that cause parsing errors.
- [x] Implement saving of messages sent to Telegram.

## Features
- [x] Add a mechanism to re-parse HTML files with updated selectors.
