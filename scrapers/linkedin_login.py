import os
import asyncio
import logging
from playwright.async_api import async_playwright
from playwright_stealth import Stealth

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
logger = logging.getLogger(__name__)


async def login():
    """
    Open a visible browser for manual LinkedIn login.
    The session is saved to .linkedin_profile/ for use by the scraper.
    """
    script_dir = os.path.dirname(os.path.abspath(__file__))
    project_root = os.path.dirname(script_dir)
    profile_dir = os.path.join(project_root, ".linkedin_profile")

    context = None
    try:
        async with Stealth().use_async(async_playwright()) as p:
            context = await p.chromium.launch_persistent_context(
                profile_dir,
                headless=False,
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
                viewport={"width": 1280, "height": 720},
                locale="en-US",
            )

            page = context.pages[0] if context.pages else await context.new_page()

            logger.info("Navigating to LinkedIn...")
            await page.goto("https://www.linkedin.com/feed/", timeout=60000)

            # Check if already logged in
            if "feed" in page.url:
                logger.info("Already logged in. Session is valid.")
                await context.close()
                return True

            # Handle login page
            if "login" in page.url or "authwall" in page.url or "signup" in page.url:
                logger.info(
                    "Not logged in. Please log in manually in the browser window. "
                    "Waiting up to 5 minutes..."
                )
                try:
                    await page.wait_for_url("**/feed/**", timeout=300000)
                    logger.info("Login successful. Session saved.")
                except Exception:
                    logger.error("Login was not completed in time.")
                    await context.close()
                    return False

            # Handle CAPTCHA
            if "checkpoint/challenge" in page.url or "security-verification" in page.url:
                logger.info(
                    "CAPTCHA detected. Please complete the check in the browser window. "
                    "Waiting up to 5 minutes..."
                )
                try:
                    await page.wait_for_function(
                        "() => !window.location.href.includes('checkpoint') && !window.location.href.includes('security-verification')",
                        timeout=300000,
                    )
                    logger.info("Security check passed. Session saved.")
                except Exception:
                    logger.error("Security check was not completed in time.")
                    await context.close()
                    return False

            await context.close()
            return True

    except Exception as e:
        logger.exception(f"Login error: {e}")
        if context:
            try:
                await context.close()
            except Exception:
                pass
        return False


if __name__ == "__main__":
    success = asyncio.run(login())
    if success:
        print("LinkedIn session is ready.")
    else:
        print("LinkedIn login failed. Try again.")
