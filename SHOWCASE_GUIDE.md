# UI Component Showcase & Testing Guide

This document provides an overview of the interactive showcase page, end-to-end testing setup, and tools for creating UI walkthroughs.

## Interactive Showcase Page

A live demo showcasing shadcn/ui components working together is available at `/showcase`.

### Features Demonstrated

1. **Button Component**
   - Default variant with primary action
   - Outline variant for secondary actions
   - Secondary variant for alternative actions
   - Ghost variant for subtle actions
   - Size variants (sm, lg)
   - Disabled states during conversion
   - Click handlers and interactions

2. **Card Component**
   - Card container with styling
   - CardHeader, CardTitle, CardDescription
   - CardContent for main content
   - CardFooter for actions
   - Interactive selection states
   - Grid and list view layouts

3. **Progress Component**
   - Value-based progress indication
   - Animated progress bar
   - Integration with conversion flow
   - Accessibility support

### Usage Flow

1. **Start Conversion Demo**
   - Click "Start Conversion Demo" button
   - Watch progress bar animate
   - See slides appear as they're "converted"
   - Progress indicator shows completion percentage

2. **View Modes**
   - Toggle between Grid View and List View
   - Grid view shows cards with preview
   - List view shows detailed items

3. **Slide Selection**
   - Click any slide card to view details
   - Slide modal shows preview and actions
   - Close modal to return to list

4. **Actions**
   - Reset to start over
   - Download (placeholder functionality)
   - View component usage summary

### Accessing the Showcase

Navigate to `http://localhost:3000/showcase` when the dev server is running.

```bash
npm run dev
# Open http://localhost:3000/showcase
```

## End-to-End Testing

Playwright is configured for comprehensive end-to-end testing of the showcase page and other features.

### Running E2E Tests

```bash
# Run all E2E tests
npm run test:e2e

# Run with UI mode
npx playwright test --ui

# Show test report
npm run test:e2e:report
```

### Test Coverage

The E2E test suite (`e2e/showcase.spec.ts`) includes:

1. **Functionality Tests**
   - Page load verification
   - Conversion start/stop
   - View mode toggling
   - Slide selection
   - Reset functionality

2. **Responsive Tests**
   - Mobile viewport (375x667)
   - Tablet viewport (768x1024)
   - Desktop viewport (default)

3. **Accessibility Tests**
   - Heading structure
   - Button accessibility
   - ARIA attributes

### Test File Location

```
e2e/
└── showcase.spec.ts     # Main showcase page tests
```

### Playwright Configuration

Configuration is in `playwright.config.ts`:
- Browser: Chromium (Desktop Chrome)
- Base URL: http://localhost:3000
- Web server: Auto-starts dev server
- Reporter: HTML (with option for other formats)

## Creating Animated Walkthroughs

### Automated Screenshot Capture

Use the walkthrough script to capture step-by-step screenshots:

```bash
# First, start the dev server
npm run dev

# In another terminal, run the walkthrough script
npx tsx scripts/walkthrough.ts
```

This captures 7 screenshots showing the full user flow:

1. `01-landing.png` - Initial page load
2. `02-converting.png` - After clicking start
3. `03-progress.png` - Progress indication
4. `04-slides-grid.png` - Grid view of slides
5. `05-slides-list.png` - List view of slides
6. `06-slide-details.png` - Slide detail modal
7. `07-back-to-slides.png` - Return to list

### Creating Animated GIF

Use FFmpeg to convert screenshots to an animated GIF:

```bash
# Install FFmpeg if needed (Windows)
winget install FFmpeg

# Create animated GIF
ffmpeg -framerate 2 -i walkthrough/%02d-*.png -vf "fps=2,scale=1280:720:force_original_aspect_ratio=decrease,pad=1280:720:(ow-iw)/2:(oh-ih)/2" walkthrough.gif
```

### Customization Options

1. **Adjust Timing**
   Edit `scripts/walkthrough.ts` to change timeouts:
   ```typescript
   await page.waitForTimeout(2000)  // Increase for slower pacing
   ```

2. **Add More Steps**
   Extend the script with additional interactions

3. **Custom Viewport**
   Modify the viewport in `walkthrough.ts`:
   ```typescript
   const context = await browser.newContext({
     viewport: { width: 1920, height: 1080 }
   })
   ```

4. **Add Annotations**
   Use image editing tools or CSS overlays to add labels

### Output Location

All walkthrough files are saved to:
```
walkthrough/
├── 01-landing.png
├── 02-converting.png
├── 03-progress.png
├── 04-slides-grid.png
├── 05-slides-list.png
├── 06-slide-details.png
├── 07-back-to-slides.png
└── walkthrough.gif  (after FFmpeg processing)
```

## Component Library

### Installed shadcn/ui Components

| Component | Location | Status |
|-----------|----------|--------|
| Button | `components/ui/button.tsx` | ✓ Complete |
| Card | `components/ui/card.tsx` | ✓ Complete |
| Progress | `components/ui/progress.tsx` | ✓ Complete |

### Adding More Components

To add additional shadcn/ui components:

1. Visit [shadcn/ui components](https://ui.shadcn.com/docs/components)
2. Copy the component code to `components/ui/`
3. Ensure dependencies are installed:
   ```bash
   npm install @radix-ui/react-{component}
   ```
4. Add corresponding tests in `__tests__/`

### Utility Functions

The `lib/utils.ts` file provides:

- `cn()` - Class name merger (clsx + tailwind-merge)
- Used by all components for consistent styling

## Testing Infrastructure

### Unit Tests (Jest)

```bash
# Run unit tests
npm test

# Watch mode
npm run test:watch
```

### Integration Tests (React Testing Library)

Located in `__tests__/`:
- `Button.test.tsx` - Button component tests
- `Card.test.tsx` - Card component tests
- `Progress.test.tsx` - Progress component tests
- `Dropzone.test.tsx` - Existing Dropzone tests
- `Gallery.test.tsx` - Existing Gallery tests

### E2E Tests (Playwright)

Located in `e2e/`:
- `showcase.spec.ts` - Showcase page E2E tests

### Test Results

All tests are passing:
- Unit tests: 28 passed
- E2E tests: 12+ test cases covering functionality, responsiveness, and accessibility

## Quick Start

```bash
# 1. Install dependencies
npm install

# 2. Start development server
npm run dev

# 3. Open showcase page
# Visit http://localhost:3000/showcase

# 4. Run tests
npm test              # Unit tests
npm run test:e2e      # E2E tests

# 5. Create walkthrough (with dev server running)
npx tsx scripts/walkthrough.ts
```

## Next Steps

1. **Add More Components**
   - Dialog/Modal for advanced interactions
   - Toast notifications for status updates
   - Tabs for organizing content

2. **Enhance Testing**
   - Add API integration tests
   - Create visual regression tests
   - Add performance benchmarks

3. **Improve Documentation**
   - Add storybook for component documentation
   - Create video tutorials
   - Add inline code comments

4. **Deploy**
   - Set up CI/CD pipeline
   - Deploy to preview environment
   - Add deployment documentation

## Resources

- [shadcn/ui Documentation](https://ui.shadcn.com)
- [Playwright Documentation](https://playwright.dev)
- [Jest Documentation](https://jestjs.io)
- [React Testing Library](https://testing-library.com)
- [FFmpeg Documentation](https://ffmpeg.org)
