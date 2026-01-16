import { chromium } from '@playwright/test'

async function captureWalkthrough() {
  const browser = await chromium.launch({ headless: true })
  const context = await browser.newContext({
    viewport: { width: 1280, height: 720 }
  })
  const page = await context.newPage()
  
  console.log('Starting UI walkthrough capture...')
  
  await page.goto('http://localhost:3000/showcase')
  await page.waitForLoadState('networkidle')
  
  console.log('✓ Page loaded')
  
  await page.screenshot({ path: 'walkthrough/01-landing.png', fullPage: true })
  console.log('✓ Screenshot 1: Landing page')
  
  const startButton = page.locator('text=Start Conversion Demo')
  await startButton.click()
  console.log('✓ Clicked Start Conversion')
  
  await page.waitForTimeout(1000)
  await page.screenshot({ path: 'walkthrough/02-converting.png', fullPage: true })
  console.log('✓ Screenshot 2: Conversion started')
  
  await page.waitForTimeout(2000)
  await page.screenshot({ path: 'walkthrough/03-progress.png', fullPage: true })
  console.log('✓ Screenshot 3: Progress shown')
  
  await page.waitForTimeout(3000)
  await page.screenshot({ path: 'walkthrough/04-slides-grid.png', fullPage: true })
  console.log('✓ Screenshot 4: Slides in grid view')
  
  const listViewButton = page.locator('text=List View')
  await listViewButton.click()
  await page.waitForTimeout(500)
  await page.screenshot({ path: 'walkthrough/05-slides-list.png', fullPage: true })
  console.log('✓ Screenshot 5: Slides in list view')
  
  const firstSlide = page.locator('[class*="rounded-xl"]').first()
  await firstSlide.click()
  await page.waitForTimeout(500)
  await page.screenshot({ path: 'walkthrough/06-slide-details.png', fullPage: true })
  console.log('✓ Screenshot 6: Slide details modal')
  
  const closeButton = page.locator('button:has-text("Close")')
  await closeButton.click()
  await page.waitForTimeout(300)
  await page.screenshot({ path: 'walkthrough/07-back-to-slides.png', fullPage: true })
  console.log('✓ Screenshot 7: Back to slides')
  
  await browser.close()
  
  console.log('\n✓ Walkthrough screenshots captured successfully!')
  console.log('📁 Location: walkthrough/*.png')
  console.log('\nTo create animated GIF, use:')
  console.log('  ffmpeg -framerate 2 -i walkthrough/%02d-slides-list.png -vf "fps=2,scale=1280:720:force_original_aspect_ratio=decrease,pad=1280:720:(ow-iw)/2:(oh-ih)/2" walkthrough.gif')
}

captureWalkthrough().catch(console.error)
