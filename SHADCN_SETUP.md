# shadcn/ui Setup Guide

This project has been set up with [shadcn/ui](https://ui.shadcn.com/) components and a comprehensive testing infrastructure.

## What's Included

### Installed Components
- **Button**: Various button variants (default, destructive, outline, secondary, ghost, link)
- **Card**: Container components for organizing content
- **Progress**: Progress indicator component
- **Utils**: `cn` utility function for className merging

### Testing Infrastructure
- Jest with jsdom environment
- React Testing Library
- User Event library for interaction testing
- Component tests for all shadcn/ui components

## Component Usage

### Button

```tsx
import { Button } from "@/components/ui/button"

// Default button
<Button>Click me</Button>

// With variant
<Button variant="outline">Outline</Button>
<Button variant="destructive">Delete</Button>
<Button variant="ghost">Ghost</Button>
<Button variant="link">Link</Button>

// With size
<Button size="sm">Small</Button>
<Button size="lg">Large</Button>

// Disabled
<Button disabled>Disabled</Button>

// With onClick
<Button onClick={() => console.log('clicked')}>Click me</Button>
```

### Card

```tsx
import { Card, CardHeader, CardTitle, CardDescription, CardContent, CardFooter } from "@/components/ui/card"

<Card>
  <CardHeader>
    <CardTitle>Card Title</CardTitle>
    <CardDescription>Optional description</CardDescription>
  </CardHeader>
  <CardContent>
    Main content goes here
  </CardContent>
  <CardFooter>
    Footer actions
  </CardFooter>
</Card>
```

### Progress

```tsx
import { Progress } from "@/components/ui/progress"

<Progress value={50} />
```

## Testing

### Running Tests

```bash
# Run all tests
npm test

# Run tests in watch mode
npm run test:watch
```

### Writing Tests

Tests follow the standard React Testing Library patterns:

```tsx
import { render, screen } from '@testing-library/react'
import { Button } from '@/components/ui/button'

describe('Button', () => {
  it('renders children correctly', () => {
    render(<Button>Click me</Button>)
    expect(screen.getByRole('button', { name: 'Click me' })).toBeInTheDocument()
  })
})
```

## Adding More Components

To add more shadcn/ui components:

1. Visit [shadcn/ui documentation](https://ui.shadcn.com/docs/components)
2. Copy the component code to `components/ui/`
3. Create a corresponding test file in `__tests__/`
4. Follow the existing test patterns

## Customization

### Colors

Theme colors are defined in `app/globals.css`:

```css
:root {
  --background: 0 0% 4%;
  --foreground: 0 0% 100%;
  --primary: 222 47% 11%;
  --primary-foreground: 210 40% 98%;
  /* ... */
}
```

### Tailwind Config

Components use Tailwind v4 CSS-based configuration. Customize styles in `app/globals.css` and component files directly.

## Project Structure

```
.
├── components/
│   ├── ui/              # shadcn/ui components
│   │   ├── button.tsx
│   │   ├── card.tsx
│   │   └── progress.tsx
│   └── Dropzone.tsx     # Existing components
├── lib/
│   └── utils.ts         # Utility functions (cn)
├── app/
│   ├── globals.css      # Global styles & theme variables
│   └── layout.tsx
├── __tests__/           # Test files
│   ├── Button.test.tsx
│   ├── Card.test.tsx
│   ├── Progress.test.tsx
│   ├── Dropzone.test.tsx
│   └── Gallery.test.tsx
└── components.json      # shadcn/ui configuration
```

## Notes

- All components are fully typed with TypeScript
- Components support Dark mode (configured in globals.css)
- Icons use Lucide React for consistency
- All components are tested with comprehensive test coverage
