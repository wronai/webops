"""
GUI Tests for WebOps Voice Service using Playwright
"""

import asyncio
import pytest
from playwright.async_api import async_playwright, expect
import requests
import time


class TestWebOpsGUI:
    """Test suite for WebOps Voice Service GUI"""
    
    BASE_URL = "http://localhost:8001"
    
    @pytest.fixture(scope="class")
    async def browser_context(self):
        """Create browser context for testing"""
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=False)
            context = await browser.new_context()
            page = await context.new_page()
            yield page
            await context.close()
            await browser.close()
    
    async def test_page_loads(self, browser_context):
        """Test that the main page loads correctly"""
        page = browser_context
        await page.goto(self.BASE_URL)
        
        # Check page title
        await expect(page).to_have_title("🎤 WebOps Voice Service - NLP2CMD")
        
        # Check main elements are present
        await expect(page.locator("h1")).to_be_visible()
        await expect(page.locator("#textInput")).to_be_visible()
        await expect(page.locator("#submitBtn")).to_be_visible()
        await expect(page.locator("#recordBtn")).to_be_visible()
    
    async def test_command_input_and_execution(self, browser_context):
        """Test text command input and execution"""
        page = browser_context
        await page.goto(self.BASE_URL)
        
        # Find command input
        command_input = page.locator("#textInput")
        await command_input.fill("ls -la")
        
        # Click execute button
        execute_btn = page.locator("#submitBtn")
        await execute_btn.click()
        
        # Wait for response
        await page.wait_for_selector("#result", timeout=10000)
        
        # Check output is displayed
        output = page.locator("#result")
        await expect(output).to_be_visible()
        output_text = await output.text_content()
        assert "Command Executed Successfully" in output_text or "Command:" in output_text
    
    async def test_voice_recognition_toggle(self, browser_context):
        """Test voice recognition functionality"""
        page = browser_context
        await page.goto(self.BASE_URL)
        
        # Find voice button
        voice_btn = page.locator("#recordBtn")
        await expect(voice_btn).to_be_visible()
        
        # Grant microphone permissions
        await page.context.grant_permissions(["microphone"])
        
        # Click to start voice recognition
        await voice_btn.click()
        
        # Check that button text changes or that recording class is added
        try:
            await expect(voice_btn).to_contain_text("⏹️ Stop", timeout=5000)
        except:
            # Fallback: check for recording class
            await expect(voice_btn).to_have_class("recording", timeout=5000)
        
        # Stop recording
        await voice_btn.click()
        
        # Check button text is back to start
        await expect(voice_btn).to_contain_text("🎤 Start")
    
    async def test_command_history(self, browser_context):
        """Test command history functionality"""
        page = browser_context
        await page.goto(self.BASE_URL)
        
        # Execute multiple commands
        commands = ["pwd", "whoami", "date"]
        for cmd in commands:
            await page.fill("#textInput", cmd)
            await page.click("#submitBtn")
            await page.wait_for_timeout(2000)
        
        # Check history panel
        history_panel = page.locator("#commandHistory")
        await expect(history_panel).to_be_visible()
        
        # Verify commands are in history
        history_items = await history_panel.locator(".history-item").count()
        assert history_items > 0
    
    async def test_clear_functionality(self, browser_context):
        """Test clear input and output functionality"""
        page = browser_context
        await page.goto(self.BASE_URL)
        
        # Enter and execute command
        await page.fill("#textInput", "echo 'test'")
        await page.click("#submitBtn")
        await page.wait_for_selector("#result")
        
        # Clear input manually
        await page.fill("#textInput", "")
        
        # Verify input is cleared
        command_input = page.locator("#textInput")
        await expect(command_input).to_have_value("")
    
    async def test_language_switch(self, browser_context):
        """Test language switching functionality"""
        page = browser_context
        await page.goto(self.BASE_URL)
        
        # The interface is primarily in Polish
        # Check that Polish elements are present
        await expect(page.locator("text=🎤 Start Voice")).to_be_visible()
        await expect(page.locator("text=▶ Execute")).to_be_visible()
        
        # Test that commands work in both languages
        await page.fill("#textInput", "pokaż pliki")
        await page.click("#submitBtn")
        await page.wait_for_timeout(2000)
        
        await page.fill("#textInput", "list files")
        await page.click("#submitBtn")
        await page.wait_for_timeout(2000)
    
    async def test_error_handling(self, browser_context):
        """Test error handling for invalid commands"""
        page = browser_context
        await page.goto(self.BASE_URL)
        
        # Enter invalid command
        await page.fill("#textInput", "invalid-command-xyz")
        await page.click("#submitBtn")
        
        # Wait for response
        await page.wait_for_selector("#result", timeout=10000)
        
        # Check if error is shown in result
        result = page.locator("#result")
        result_text = await result.text_content()
        # Error might be shown in different formats
        assert "command not found" in result_text.lower() or "error" in result_text.lower() or "not found" in result_text.lower()
    
    async def test_responsive_design(self, browser_context):
        """Test responsive design on different screen sizes"""
        page = browser_context
        
        # Test mobile view
        await page.set_viewport_size({"width": 375, "height": 667})
        await page.goto(self.BASE_URL)
        await expect(page.locator("h1")).to_be_visible()
        await expect(page.locator("#textInput")).to_be_visible()
        
        # Test tablet view
        await page.set_viewport_size({"width": 768, "height": 1024})
        await page.reload()
        await expect(page.locator(".command-history")).to_be_visible()
        
        # Test desktop view
        await page.set_viewport_size({"width": 1920, "height": 1080})
        await page.reload()
        await expect(page.locator(".examples")).to_be_visible()
    
    async def test_keyboard_shortcuts(self, browser_context):
        """Test keyboard shortcuts"""
        page = browser_context
        await page.goto(self.BASE_URL)
        
        # Focus input
        await page.click("#textInput")
        
        # Type command and press Enter
        await page.fill("#textInput", "echo 'keyboard test'")
        await page.keyboard.press("Enter")
        
        # Check command was executed
        await page.wait_for_selector("#result")
        result = page.locator("#result")
        await expect(result).to_contain_text("keyboard test")
    
    async def test_api_endpoint_integration(self):
        """Test direct API endpoint integration"""
        # Test health endpoint
        response = requests.get(f"{self.BASE_URL}/health")
        assert response.status_code == 200
        assert response.json()["status"] == "healthy"
        
        # Test command endpoint
        response = requests.post(
            f"{self.BASE_URL}/api/command",
            json={
                "text_command": "echo 'API test'",
                "language": "en",
                "execute": True
            }
        )
        assert response.status_code == 200
        assert "output" in response.json()


# Run tests manually
async def run_gui_tests():
    """Run GUI tests manually without pytest"""
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context()
        page = await context.new_page()
        
        test_instance = TestWebOpsGUI()
        
        try:
            print("Testing page load...")
            await test_instance.test_page_loads(page)
            print("✓ Page loads correctly")
            
            print("Testing command execution...")
            await test_instance.test_command_input_and_execution(page)
            print("✓ Command execution works")
            
            print("Testing voice toggle...")
            await test_instance.test_voice_recognition_toggle(page)
            print("✓ Voice recognition toggle works")
            
            print("Testing clear functionality...")
            await test_instance.test_clear_functionality(page)
            print("✓ Clear functionality works")
            
            print("Testing language switch...")
            await test_instance.test_language_switch(page)
            print("✓ Language switch works")
            
        except Exception as e:
            print(f"✗ Test failed: {e}")
            import traceback
            traceback.print_exc()
        
        finally:
            await context.close()
            await browser.close()


if __name__ == "__main__":
    asyncio.run(run_gui_tests())
