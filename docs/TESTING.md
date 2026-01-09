# Testing Guide

This document describes the automated testing infrastructure for Plum-Snapcast.

## Overview

Plum-Snapcast uses a comprehensive testing strategy:

- **Backend**: Python tests with pytest
- **Frontend**: TypeScript tests with Vitest + React Testing Library
- **CI/CD**: GitHub Actions for automated testing on every PR
- **Mocks**: All tests use mocks to run without a live backend

## Quick Start

### Running Backend Tests

```bash
# Navigate to backend directory
cd backend

# Install test dependencies
pip install -r tests/requirements-test.txt
pip install flask flask-cors

# Run all tests
python -m pytest tests/

# Run with coverage
python -m pytest tests/ --cov=scripts --cov-report=html

# Run specific test file
python -m pytest tests/unit/test_settings_api.py

# Run specific test
python -m pytest tests/unit/test_settings_api.py::TestSettingsAPI::test_get_settings_returns_defaults
```

### Running Frontend Tests

```bash
# Navigate to frontend directory
cd frontend

# Install dependencies
npm install

# Run tests in watch mode
npm test

# Run tests once
npm run test:run

# Run with coverage
npm run test:coverage
```

## Test Structure

### Backend Tests

```
backend/tests/
├── conftest.py              # Shared fixtures
├── pytest.ini               # Pytest configuration
├── requirements-test.txt    # Test dependencies
├── unit/
│   ├── test_settings_api.py
│   ├── test_playback_api.py
│   ├── test_integrations_api.py
│   ├── test_audio_api.py
│   └── federation/
│       ├── test_discovery.py
│       ├── test_websocket_manager.py
│       ├── test_router.py
│       └── test_api.py
├── integration/
│   └── test_settings_flow.py
└── mocks/
    ├── mock_subprocess.py
    ├── mock_filesystem.py
    ├── mock_avahi.py
    └── mock_websocket.py
```

### Frontend Tests

```
frontend/tests/
├── setup.ts                 # Test setup and global mocks
├── unit/
│   ├── services/
│   │   ├── settingsService.test.ts
│   │   ├── playbackService.test.ts
│   │   ├── federationService.test.ts
│   │   ├── integrationsService.test.ts
│   │   └── audioService.test.ts
│   ├── hooks/
│   │   ├── useAudioSync.test.ts
│   │   └── useBrowserAudioClient.test.ts
│   └── components/
│       ├── NowPlaying.test.tsx
│       └── PlayerControls.test.tsx
├── integration/
│   └── (integration tests)
└── mocks/
    ├── mockTypes.ts         # Type factories
    ├── mockWebSocket.ts     # WebSocket mock
    └── mockFetch.ts         # MSW handlers
```

## Test Categories

### Unit Tests

Test individual functions, classes, and components in isolation:

- **API endpoints**: Request/response handling
- **Services**: Business logic and API calls
- **Hooks**: State management and side effects
- **Components**: Rendering and user interactions

### Integration Tests

Test complete flows across multiple components:

- Settings read/write/update flow
- Integration enable/disable lifecycle
- Federation server discovery and routing

## Mock Strategy

All tests use mocks to avoid requiring a running backend:

### Backend Mocks

| Mock | Purpose |
|------|---------|
| `mock_subprocess` | Mocks supervisorctl for service control |
| `mock_filesystem` | Virtual file system for settings.json |
| `mock_avahi` | Mocks mDNS discovery |
| `mock_websocket` | Mocks WebSocket connections for federation |

### Frontend Mocks

| Mock | Purpose |
|------|---------|
| `mockTypes.ts` | Factory functions for test data |
| `mockWebSocket.ts` | Custom WebSocket class for snapcastService |
| `mockFetch.ts` | MSW handlers for REST API endpoints |

## Writing Tests

### Backend Test Example

```python
import pytest
from flask import Flask

class TestSettingsAPI:
    def test_get_settings_returns_defaults(self, settings_client):
        """GET /api/settings returns default settings"""
        response = settings_client.get('/api/settings')

        assert response.status_code == 200
        data = response.get_json()
        assert 'deviceName' in data
        assert 'integrations' in data
```

### Frontend Test Example

```typescript
import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'

describe('PlayerControls', () => {
  it('should render play button when not playing', () => {
    render(<PlayerControls isPlaying={false} />)

    expect(screen.getByRole('button', { name: /play/i })).toBeInTheDocument()
  })
})
```

## Using Fixtures

### Backend Fixtures

```python
# Available fixtures from conftest.py

def test_with_settings(settings_client, temp_settings_file):
    """settings_client provides Flask test client"""
    response = settings_client.get('/api/settings')
    assert response.status_code == 200

def test_with_mock_subprocess(mock_subprocess):
    """mock_subprocess mocks supervisorctl calls"""
    # Your test code
    pass
```

### Frontend Mocks

```typescript
import { createMockStream, createMockSettings } from '../mocks/mockTypes'
import { server, setMockSettings } from '../mocks/mockFetch'

describe('MyTest', () => {
  beforeAll(() => server.listen())
  afterEach(() => server.resetHandlers())
  afterAll(() => server.close())

  it('uses mock data', () => {
    const stream = createMockStream({ isPlaying: true })
    expect(stream.isPlaying).toBe(true)
  })
})
```

## CI/CD

Tests run automatically on every push and pull request to `main`:

```yaml
# .github/workflows/test.yml

- Backend tests with coverage
- Frontend tests with coverage
- Lint check
- TypeScript type check
- Build verification
```

### Viewing CI Results

1. Go to the Actions tab in GitHub
2. Click on the workflow run
3. View test results and download coverage reports

## Coverage

### Running Coverage Locally

```bash
# Backend
cd backend
python -m pytest tests/ --cov=scripts --cov-report=html
open htmlcov/index.html

# Frontend
cd frontend
npm run test:coverage
open coverage/index.html
```

### Coverage Goals

- **Backend**: 70%+ line coverage
- **Frontend**: 60%+ line coverage

## Common Issues

### Backend Tests

**Import errors**: Ensure Flask and dependencies are installed:
```bash
pip install flask flask-cors
```

**Path issues**: The conftest.py adds `scripts/` to the Python path automatically.

### Frontend Tests

**MSW setup**: Ensure server is started before tests:
```typescript
beforeAll(() => server.listen())
afterAll(() => server.close())
```

**Async tests**: Use `await` with async operations:
```typescript
it('fetches data', async () => {
  const response = await fetch('/api/settings')
  expect(response.ok).toBe(true)
})
```

## Adding New Tests

### Backend

1. Create test file in appropriate directory (`unit/` or `integration/`)
2. Import fixtures from conftest.py
3. Use pytest conventions: `test_` prefix for functions

### Frontend

1. Create test file with `.test.ts` or `.test.tsx` extension
2. Import from vitest and testing-library
3. Use mocks from `tests/mocks/`

## Best Practices

1. **Test behavior, not implementation**: Focus on what the code does, not how
2. **Use descriptive names**: Test names should describe expected behavior
3. **Keep tests independent**: Each test should run in isolation
4. **Mock external dependencies**: Use mocks for APIs, file system, etc.
5. **Test edge cases**: Include error handling and boundary conditions
6. **Run tests before committing**: Ensure all tests pass locally
