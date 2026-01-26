#!/usr/bin/env python3
"""
GUI Test Runner for WebOps Voice Service
"""

import asyncio
import subprocess
import sys
import time
import os
from pathlib import Path


def install_playwright_browsers():
    """Install Playwright browsers"""
    print("Installing Playwright browsers...")
    result = subprocess.run(
        [sys.executable, "-m", "playwright", "install", "chromium"],
        capture_output=True,
        text=True
    )
    if result.returncode != 0:
        print(f"Failed to install Playwright browsers: {result.stderr}")
        return False
    print("✓ Playwright browsers installed")
    return True


def check_service_running():
    """Check if WebOps service is running"""
    import requests
    try:
        response = requests.get("http://localhost:8001/health", timeout=5)
        return response.status_code == 200
    except:
        return False


def run_tests_with_pytest():
    """Run tests using pytest"""
    print("Running GUI tests with pytest...")
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "test_gui.py", "-v", "-m", "gui"],
        cwd=Path(__file__).parent
    )
    return result.returncode == 0


async def run_tests_manual():
    """Run tests manually without pytest"""
    print("Running GUI tests manually...")
    from test_gui import run_gui_tests
    try:
        await run_gui_tests()
        return True
    except Exception as e:
        print(f"Manual test execution failed: {e}")
        return False


def main():
    """Main test runner"""
    print("=== WebOps GUI Test Runner ===\n")
    
    # Check if service is running
    print("1. Checking if WebOps service is running...")
    if not check_service_running():
        print("✗ WebOps service is not running on http://localhost:8001")
        print("Please start the service with: docker-compose up -d webops-voice")
        sys.exit(1)
    print("✓ WebOps service is running\n")
    
    # Install dependencies if needed
    requirements_file = Path(__file__).parent / "requirements-gui.txt"
    if requirements_file.exists():
        print("2. Installing GUI test dependencies...")
        result = subprocess.run(
            [sys.executable, "-m", "pip", "install", "-r", str(requirements_file)]
        )
        if result.returncode != 0:
            print("✗ Failed to install dependencies")
            sys.exit(1)
        print("✓ Dependencies installed\n")
    
    # Install Playwright browsers
    print("3. Installing Playwright browsers...")
    if not install_playwright_browsers():
        print("✗ Failed to install Playwright browsers")
        sys.exit(1)
    print()
    
    # Run tests
    print("4. Running GUI tests...\n")
    
    # Try pytest first
    try:
        success = run_tests_with_pytest()
    except Exception as e:
        print(f"Pytest execution failed: {e}")
        print("Falling back to manual test execution...\n")
        success = asyncio.run(run_tests_manual())
    
    if success:
        print("\n✓ All GUI tests passed!")
    else:
        print("\n✗ Some GUI tests failed")
        sys.exit(1)


if __name__ == "__main__":
    main()
