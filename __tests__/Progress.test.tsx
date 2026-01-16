import React from 'react'
import { render, screen } from '@testing-library/react'
import { Progress } from '@/components/ui/progress'
import '@testing-library/jest-dom'

describe('Progress', () => {
  it('renders progress bar', () => {
    render(<Progress value={50} />)
    const progress = screen.getByRole('progressbar')
    expect(progress).toBeInTheDocument()
  })

  it('renders with value', () => {
    render(<Progress value={75} />)
    const progress = screen.getByRole('progressbar')
    expect(progress).toBeInTheDocument()
  })

  it('handles zero value', () => {
    render(<Progress value={0} />)
    const progress = screen.getByRole('progressbar')
    expect(progress).toBeInTheDocument()
  })

  it('handles full value', () => {
    render(<Progress value={100} />)
    const progress = screen.getByRole('progressbar')
    expect(progress).toBeInTheDocument()
  })

  it('handles undefined value', () => {
    render(<Progress />)
    const progress = screen.getByRole('progressbar')
    expect(progress).toBeInTheDocument()
  })

  it('applies custom className', () => {
    const { container } = render(<Progress value={50} className="custom-progress" />)
    const progress = container.querySelector('.custom-progress')
    expect(progress).toBeInTheDocument()
  })

  it('renders indicator with correct width', () => {
    const { container } = render(<Progress value={50} />)
    const indicator = container.querySelector('[class*="transition-all"]')
    expect(indicator).toBeInTheDocument()
    const style = indicator?.getAttribute('style')
    expect(style).toContain('translateX(-50%)')
  })
})
