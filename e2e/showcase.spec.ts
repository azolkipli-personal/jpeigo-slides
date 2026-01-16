import { test, expect } from '@playwright/test'

test.describe('Showcase Page', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/showcase')
  })

  test('should load the showcase page with all components', async ({ page }) => {
    await expect(page.locator('h1')).toContainText('UI Component Showcase')
    await expect(page.locator('text=Start Conversion Demo')).toBeVisible()
    await expect(page.locator('text=Component Usage Summary')).toBeVisible()
  })

  test('should start conversion when button is clicked', async ({ page }) => {
    const startButton = page.locator('text=Start Conversion Demo')
    await expect(startButton).toBeEnabled()
    
    await startButton.click()
    
    await expect(page.locator('text=Converting Presentation')).toBeVisible()
    await expect(page.locator('text=Processing slides')).toBeVisible()
    
    const progressBar = page.locator('[role="progressbar"]')
    await expect(progressBar).toBeVisible()
  })

  test('should show converted slides after conversion completes', async ({ page }) => {
    const startButton = page.locator('text=Start Conversion Demo')
    await startButton.click()
    
    await expect(page.locator('h2:has-text("Converted Slides")')).toBeVisible({ timeout: 10000 })
    
    const slideCards = page.locator('[class*="rounded-xl"]')
    await expect(slideCards.first()).toBeVisible()
  })

  test('should toggle between grid and list view', async ({ page }) => {
    const startButton = page.locator('text=Start Conversion Demo')
    await startButton.click()
    
    await expect(page.locator('h2:has-text("Converted Slides")')).toBeVisible({ timeout: 10000 })
    
    const gridViewButton = page.locator('text=Grid View')
    const listViewButton = page.locator('text=List View')
    
    await expect(gridViewButton).toHaveClass(/bg-primary/)
    await listViewButton.click()
    await expect(listViewButton).toHaveClass(/bg-primary/)
    await expect(gridViewButton).not.toHaveClass(/bg-primary/)
  })

  test('should select a slide when clicked', async ({ page }) => {
    const startButton = page.locator('text=Start Conversion Demo')
    await startButton.click()
    
    await expect(page.locator('h2:has-text("Converted Slides")')).toBeVisible({ timeout: 10000 })
    
    const firstSlide = page.locator('[class*="rounded-xl"]').first()
    await firstSlide.click()
    
    await expect(page.locator('text=Slide 1: Welcome Slide')).toBeVisible()
  })

  test('should reset conversion state', async ({ page }) => {
    const startButton = page.locator('text=Start Conversion Demo')
    await startButton.click()
    
    await expect(page.locator('h2:has-text("Converted Slides")')).toBeVisible({ timeout: 10000 })
    
    const resetButton = page.locator('text=Reset')
    await expect(resetButton).toBeEnabled()
    await resetButton.click()
    
    await expect(page.locator('text=Converted Slides')).not.toBeVisible()
  })

  test('should show component usage summary', async ({ page }) => {
    await expect(page.locator('text=Component Usage Summary')).toBeVisible()
    await expect(page.locator('text=Button')).toBeVisible()
    await expect(page.locator('text=Card')).toBeVisible()
    await expect(page.locator('text=Progress')).toBeVisible()
  })

  test('should handle disabled states during conversion', async ({ page }) => {
    const startButton = page.locator('text=Start Conversion Demo')
    await startButton.click()
    
    await expect(startButton).toBeDisabled()
    await expect(page.locator('text=Reset')).toBeDisabled()
  })
})

test.describe('Showcase Page - Responsive', () => {
  test('should be responsive on mobile', async ({ page }) => {
    await page.setViewportSize({ width: 375, height: 667 })
    await page.goto('/showcase')
    
    await expect(page.locator('h1')).toContainText('UI Component Showcase')
    await expect(page.locator('text=Start Conversion Demo')).toBeVisible()
  })

  test('should be responsive on tablet', async ({ page }) => {
    await page.setViewportSize({ width: 768, height: 1024 })
    await page.goto('/showcase')
    
    await expect(page.locator('h1')).toContainText('UI Component Showcase')
    await expect(page.locator('text=Start Conversion Demo')).toBeVisible()
  })
})

test.describe('Showcase Page - Accessibility', () => {
  test('should have proper heading structure', async ({ page }) => {
    await page.goto('/showcase')
    
    const h1 = page.locator('h1').first()
    await expect(h1).toHaveCount(1)
    
    const h2 = page.locator('h2')
    await expect(h2.count()).toBeGreaterThanOrEqual(2)
  })

  test('should have accessible buttons', async ({ page }) => {
    await page.goto('/showcase')
    
    const buttons = page.locator('button')
    await expect(buttons.first()).toBeVisible()
  })
})
