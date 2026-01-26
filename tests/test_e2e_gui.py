"""
End-to-End GUI Tests for WebOps Voice Service
Tests complete workflows from user interaction to command execution
"""

import asyncio
import pytest
from playwright.async_api import async_playwright, expect
import requests
import json
import time


class TestE2EWorkflows:
    """E2E test suite for complete user workflows"""
    
    BASE_URL = "http://localhost:8001"
    
    @pytest.fixture(scope="class")
    async def browser_context(self):
        """Create browser context for testing"""
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=False)
            context = await browser.new_context(
                viewport={"width": 1280, "height": 720},
                locale="en-US"
            )
            page = await context.new_page()
            yield page
            await context.close()
            await browser.close()
    
    async def test_complete_voice_command_workflow(self, browser_context):
        """Test complete workflow from voice input to command execution"""
        page = browser_context
        await page.goto(self.BASE_URL)
        
        # Click voice button
        voice_btn = page.locator("#voice-btn")
        await voice_btn.click()
        
        # Simulate voice input (would normally use microphone)
        # For testing, we'll use text input as fallback
        await page.fill("#command-input", "utwórz plik testowy.txt")
        
        # Execute command
        await page.click("#execute-btn")
        
        # Wait for execution
        await page.wait_for_selector("#output", timeout=15000)
        
        # Verify command was executed
        output = page.locator("#output")
        await expect(output).to_be_visible()
        
        # Check if file was created via API
        response = requests.post(f"{self.BASE_URL}/api/command", json={
            "text_command": "ls -la testowy.txt",
            "language": "pl",
            "execute": True
        })
        assert response.status_code == 200
        assert "testowy.txt" in response.json()["output"]
    
    async def test_multilingual_command_execution(self, browser_context):
        """Test commands in multiple languages"""
        page = browser_context
        
        # Test Polish commands
        await page.goto(self.BASE_URL)
        await page.select_option("#language-selector", "pl")
        
        polish_commands = [
            ("pokaż pliki", "ls"),
            ("idź do katalogu domowego", "cd ~"),
            ("pokaż aktualną ścieżkę", "pwd")
        ]
        
        for cmd, expected in polish_commands:
            await page.fill("#command-input", cmd)
            await page.click("#execute-btn")
            await page.wait_for_timeout(3000)
            
            # Check in history
            history = page.locator("#history-panel")
            await expect(history.locator(f"text={cmd}")).to_be_visible()
        
        # Test English commands
        await page.select_option("#language-selector", "en")
        
        english_commands = [
            ("list files", "ls"),
            ("go to home directory", "cd ~"),
            ("show current path", "pwd")
        ]
        
        for cmd, expected in english_commands:
            await page.fill("#command-input", cmd)
            await page.click("#execute-btn")
            await page.wait_for_timeout(3000)
            
            # Check in history
            history = page.locator("#history-panel")
            await expect(history.locator(f"text={cmd}")).to_be_visible()
    
    async def test_command_chaining_workflow(self, browser_context):
        """Test chaining multiple commands"""
        page = browser_context
        await page.goto(self.BASE_URL)
        
        # Create a directory and navigate to it
        await page.fill("#command-input", "mkdir -p test_project/src")
        await page.click("#execute-btn")
        await page.wait_for_timeout(2000)
        
        await page.fill("#command-input", "cd test_project")
        await page.click("#execute-btn")
        await page.wait_for_timeout(2000)
        
        await page.fill("#command-input", "touch src/main.py")
        await page.click("#execute-btn")
        await page.wait_for_timeout(2000)
        
        await page.fill("#command-input", "echo 'print(\"Hello\")' > src/main.py")
        await page.click("#execute-btn")
        await page.wait_for_timeout(2000)
        
        # Verify the workflow
        await page.fill("#command-input", "cat src/main.py")
        await page.click("#execute-btn")
        await page.wait_for_selector("#output")
        
        output = page.locator("#output")
        await expect(output).to_contain_text("Hello")
    
    async def test_file_upload_and_execution(self, browser_context):
        """Test uploading a file and executing commands on it"""
        page = browser_context
        await page.goto(self.BASE_URL)
        
        # Create a test script file
        test_script = """
#!/bin/bash
echo "Test script executed"
date
whoami
"""
        
        # Save script to temporary file
        with open("/tmp/test_script.sh", "w") as f:
            f.write(test_script)
        
        # Upload file (if upload functionality exists)
        file_input = page.locator("#file-input")
        if await file_input.is_visible():
            await file_input.set_input_files("/tmp/test_script.sh")
            await page.click("#upload-btn")
            await page.wait_for_timeout(2000)
        
        # Execute the script
        await page.fill("#command-input", "chmod +x test_script.sh && ./test_script.sh")
        await page.click("#execute-btn")
        await page.wait_for_selector("#output")
        
        output = page.locator("#output")
        await expect(output).to_contain_text("Test script executed")
    
    async def test_real_time_output_streaming(self, browser_context):
        """Test real-time output streaming for long-running commands"""
        page = browser_context
        await page.goto(self.BASE_URL)
        
        # Run a command that produces output over time
        await page.fill("#command-input", "for i in {1..5}; do echo \"Step $i\"; sleep 1; done")
        await page.click("#execute-btn")
        
        # Check that output appears incrementally
        output = page.locator("#output")
        await expect(output).to_be_visible()
        
        # Wait for streaming to complete
        for i in range(1, 6):
            await expect(output).to_contain_text(f"Step {i}", timeout=2000)
    
    async def test_error_recovery_workflow(self, browser_context):
        """Test error handling and recovery"""
        page = browser_context
        await page.goto(self.BASE_URL)
        
        # Execute an invalid command
        await page.fill("#command-input", "this-command-does-not-exist")
        await page.click("#execute-btn")
        
        # Check error message
        await expect(page.locator(".error-message")).to_be_visible()
        
        # Clear and try a valid command
        await page.click("#clear-btn")
        await page.fill("#command-input", "echo 'Recovered from error'")
        await page.click("#execute-btn")
        
        # Verify successful execution
        output = page.locator("#output")
        await expect(output).to_contain_text("Recovered from error")
    
    async def test_workspace_persistence(self, browser_context):
        """Test that workspace state persists across sessions"""
        page = browser_context
        await page.goto(self.BASE_URL)
        
        # Create a file in workspace
        await page.fill("#command-input", "echo 'Persistent data' > workspace_test.txt")
        await page.click("#execute-btn")
        await page.wait_for_timeout(2000)
        
        # Reload page
        await page.reload()
        await page.wait_for_load_state("networkidle")
        
        # Check file still exists
        await page.fill("#command-input", "cat workspace_test.txt")
        await page.click("#execute-btn")
        await page.wait_for_selector("#output")
        
        output = page.locator("#output")
        await expect(output).to_contain_text("Persistent data")
    
    async def test_keyboard_shortcuts_efficiency(self, browser_context):
        """Test efficiency of keyboard shortcuts"""
        page = browser_context
        await page.goto(self.BASE_URL)
        
        # Test Ctrl+C to stop command
        await page.fill("#command-input", "sleep 10")
        await page.click("#execute-btn")
        await page.wait_for_timeout(1000)
        await page.keyboard.press("Control+KeyC")
        
        # Should stop quickly
        await page.wait_for_timeout(1000)
        
        # Test Tab completion (if implemented)
        await page.fill("#command-input", "ls ")
        await page.keyboard.press("Tab")
        # Check if completion occurred
        
        # Test Ctrl+R for search (if implemented)
        await page.keyboard.press("Control+KeyR")
        # Check if search dialog appears
    
    async def test_accessibility_features(self, browser_context):
        """Test accessibility features of the GUI"""
        page = browser_context
        await page.goto(self.BASE_URL)
        
        # Test ARIA labels
        await expect(page.locator("aria-label=Command input")).to_be_visible()
        await expect(page.locator("aria-label=Execute command")).to_be_visible()
        
        # Test keyboard navigation
        await page.keyboard.press("Tab")
        focused = await page.evaluate("document.activeElement.tagName")
        assert focused in ["INPUT", "BUTTON"]
        
        # Test screen reader compatibility
        await page.fill("#command-input", "echo 'Accessibility test'")
        await page.keyboard.press("Enter")
        
        # Check if output is properly announced
        output = page.locator("#output[role='status']")
        if await output.is_visible():
            await expect(output).to_have_attribute("aria-live", "polite")


# Performance tests
class TestPerformance:
    """Performance tests for the GUI"""
    
    async def test_page_load_performance(self):
        """Test page load time"""
        import time
        start_time = time.time()
        
        response = requests.get("http://localhost:8001")
        load_time = time.time() - start_time
        
        assert load_time < 2.0, f"Page load took {load_time:.2f}s, expected < 2.0s"
        assert response.status_code == 200
    
    async def test_command_response_time(self):
        """Test command execution response time"""
        start_time = time.time()
        
        response = requests.post(
            "http://localhost:8001/api/command",
            json={
                "text_command": "echo 'Performance test'",
                "language": "en",
                "execute": True
            }
        )
        
        response_time = time.time() - start_time
        assert response_time < 5.0, f"Command took {response_time:.2f}s, expected < 5.0s"
        assert response.status_code == 200


if __name__ == "__main__":
    # Run a quick manual test
    async def quick_test():
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=False)
            context = await browser.new_context()
            page = await context.new_page()
            
            test = TestE2EWorkflows()
            try:
                await test.test_complete_voice_command_workflow(page)
                print("✓ E2E workflow test passed")
            except Exception as e:
                print(f"✗ E2E workflow test failed: {e}")
            
            await context.close()
            await browser.close()
    
    asyncio.run(quick_test())
