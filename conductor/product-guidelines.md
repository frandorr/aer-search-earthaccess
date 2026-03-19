# Product Guidelines

## Prose & Communication
- **Tone:** Professional, technical, and concise.
- **Audience:** Developers and data scientists.
- **Clarity:** Use precise technical terms. Avoid jargon unless standard in the field (e.g., STAC, granules).
- **Naming:** Consistent with `aer` and Earthdata standards.

## Code Design & Principles
- **Modularity:** Adhere to Polylith principles—keep logic in components, use bases for interfaces.
- **Type Safety:** Use Type Hints extensively for clarity and better IDE support.
- **Error Handling:** Use custom exceptions for better error diagnostics.
- **Test-Driven Development (TDD):** Write tests before or alongside implementation.

## UX & API Principles
- **Intuitive Interface:** Maintain consistency with other `aer` search plugins.
- **Granular Control:** Allow users to specify search parameters effectively.
- **Informative Metadata:** Ensure returned metadata is rich and follows the standardized `aer` format.
- **Authentication:** Provide clear mechanisms for NASA Earthdata credentials management.
