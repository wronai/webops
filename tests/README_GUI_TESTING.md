# GUI Testing for WebOps Voice Service

This directory contains comprehensive GUI tests for the WebOps Voice Service using Playwright.

## Setup

### Prerequisites
- WebOps Voice Service running on `http://localhost:8001`
- Python 3.8+
- Docker (for running the service)

### Installation

1. Install test dependencies:
```bash
pip install -r requirements-gui.txt
```

2. Install Playwright browsers:
```bash
python -m playwright install chromium
```

## Running Tests

### Quick Start
```bash
# Run all GUI tests
./run_gui_tests.py

# Or run with pytest directly
pytest test_gui.py -v -m gui
```

### Test Categories

1. **Basic GUI Tests** (`test_gui.py`)
   - Page loading
   - Command input and execution
   - Voice recognition toggle
   - Command history
   - Clear functionality
   - Language switching
   - Error handling
   - Responsive design
   - Keyboard shortcuts
   - API integration

2. **End-to-End Tests** (`test_e2e_gui.py`)
   - Complete voice command workflows
   - Multilingual command execution
   - Command chaining
   - File upload and execution
   - Real-time output streaming
   - Error recovery
   - Workspace persistence
   - Keyboard shortcuts efficiency
   - Accessibility features
   - Performance tests

### Running Specific Tests

```bash
# Run only basic GUI tests
pytest test_gui.py::TestWebOpsGUI::test_page_loads -v

# Run only E2E tests
pytest test_e2e_gui.py -v

# Run performance tests only
pytest test_e2e_gui.py::TestPerformance -v

# Run tests without GUI (headless)
pytest test_gui.py -v --headed=false

# Run with debug mode
pytest test_gui.py -v -s --tb=long
```

## Test Configuration

### pytest.ini
- Configures async test execution
- Sets test discovery patterns
- Defines custom markers

### Environment Variables
- `GUI_TEST_HEADLESS`: Set to `true` for headless mode
- `GUI_TEST_SLOWMO`: Add delay between actions (in ms)
- `GUI_TEST_TIMEOUT`: Custom timeout for test operations

Example:
```bash
GUI_TEST_HEADLESS=true GUI_TEST_SLOWMO=500 pytest test_gui.py
```

## Writing New Tests

### Basic Test Structure
```python
import pytest
from playwright.async_api import expect

class TestNewFeature:
    async def test_new_functionality(self, browser_context):
        page = browser_context
        await page.goto("http://localhost:8001")
        
        # Your test code here
        await expect(page.locator("#new-element")).to_be_visible()
```

### Best Practices
1. Use `await expect()` for assertions
2. Wait for elements with explicit timeouts
3. Use descriptive test names
4. Test both positive and negative scenarios
5. Clean up after tests (delete created files, etc.)

### Locators
- Use CSS selectors or text content
- Prefer semantic selectors (`#command-input`) over XPath
- Use `data-testid` attributes for complex elements

## Debugging

### Visual Debugging
```bash
# Run with headed mode to see browser
pytest test_gui.py -v --headed=true

# Run with slow motion
pytest test_gui.py -v --slowmo=1000
```

### Screenshots
Tests automatically capture screenshots on failure. You can also manually capture:
```python
await page.screenshot(path="test_failure.png")
```

### Video Recording
```python
# In test setup
context = await browser.new_context(record_video_dir="videos/")
```

## Continuous Integration

### GitHub Actions Example
```yaml
name: GUI Tests
on: [push, pull_request]
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v2
      - name: Setup Python
        uses: actions/setup-python@v2
        with:
          python-version: 3.9
      - name: Install dependencies
        run: |
          pip install -r requirements-gui.txt
          python -m playwright install chromium
      - name: Start service
        run: docker-compose up -d webops-voice
      - name: Run tests
        run: pytest test_gui.py -v
```

## Troubleshooting

### Common Issues

1. **Service not running**
   - Ensure Docker container is running: `docker-compose up -d webops-voice`
   - Check service health: `curl http://localhost:8001/health`

2. **Browser not installed**
   - Run: `python -m playwright install chromium`

3. **Tests timing out**
   - Increase timeout in test or use `--timeout` flag
   - Check if service is responding slowly

4. **Element not found**
   - Verify selector is correct
   - Add explicit wait: `await page.wait_for_selector("#element")`

### Debug Mode
Run tests with extra logging:
```bash
DEBUG=true pytest test_gui.py -v -s
```

## Performance Benchmarks

Expected performance metrics:
- Page load: < 2 seconds
- Command execution: < 5 seconds
- Voice recognition toggle: < 1 second
- History panel update: < 500ms

## Contributing

When adding new GUI tests:
1. Follow existing naming conventions
2. Add appropriate markers (`@pytest.mark.gui`)
3. Update this README if adding new test categories
4. Ensure tests are independent and can run in any order

## Additional Resources

- [Playwright Documentation](https://playwright.dev/python/)
- [Pytest Documentation](https://docs.pytest.org/)
- [Async/Await in Python](https://docs.python.org/3/library/asyncio.html)
