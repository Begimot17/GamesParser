# Project Management Guide

This document provides a unified guide for managing the GamesParser project.

## Bug Tracking

- **Reporting:** When a bug is found, create a new issue in the project's issue tracker.
- **Fixing:** When fixing a bug, create a new branch from `main`. Once the fix is complete, create a pull request to merge the changes back into `main`.

## Refactoring

- **Goal:** Continuously improve the codebase for better readability, maintainability, and performance.
- **Process:**
    1. Identify areas for improvement.
    2. Create a new branch for the refactoring task.
    3. Apply the changes, ensuring that all tests pass.
    4. Create a pull request with a clear description of the changes.

## Testing

- **Strategy:**
    - **Unit Tests:** For individual components and functions.
    - **Integration Tests:** To test the interaction between different parts of the system.
- **Guidelines:**
    - All new features must be accompanied by tests.
    - All bug fixes must include a test that reproduces the bug.

## Logging

- **Levels:**
    - `INFO`: General information about the application's state.
    - `WARNING`: Indicates a potential problem that doesn't prevent the application from running.
    - `ERROR`: A serious error that prevents the application from functioning correctly.
- **Storage:**
    - Warning and error logs should be saved to a separate file for later analysis.
    - HTML content of parsed pages should be saved to facilitate debugging of selectors and formatting.
    - Messages sent to Telegram should be logged for auditing purposes.

## Code Style

- **Consistency:** Follow the PEP 8 style guide for Python code.
- **Linting:** Use a linter to enforce a consistent code style.
