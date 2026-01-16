'use client'

import React, { useState, useEffect } from 'react'
import { Button } from '@/components/ui/button'
import { Card, CardHeader, CardTitle, CardDescription, CardContent, CardFooter } from '@/components/ui/card'
import { Progress } from '@/components/ui/progress'

interface DemoSlide {
  id: number
  title: string
  description: string
  imageUrl?: string
}

const DEMO_SLIDES: DemoSlide[] = [
  {
    id: 1,
    title: 'Welcome Slide',
    description: 'Introduction to the presentation'
  },
  {
    id: 2,
    title: 'Agenda',
    description: 'Overview of topics to be covered'
  },
  {
    id: 3,
    title: 'Main Content',
    description: 'Detailed information and examples'
  },
  {
    id: 4,
    title: 'Conclusion',
    description: 'Summary and next steps'
  },
  {
    id: 5,
    title: 'Q&A',
    description: 'Questions and answers session'
  }
]

export default function ShowcasePage() {
  const [isConverting, setIsConverting] = useState(false)
  const [progress, setProgress] = useState(0)
  const [convertedSlides, setConvertedSlides] = useState<DemoSlide[]>([])
  const [selectedSlide, setSelectedSlide] = useState<DemoSlide | null>(null)
  const [viewMode, setViewMode] = useState<'grid' | 'list'>('grid')

  const handleStartConversion = () => {
    setIsConverting(true)
    setProgress(0)
    setConvertedSlides([])

    const totalSlides = DEMO_SLIDES.length
    let currentSlide = 0

    const interval = setInterval(() => {
      currentSlide++
      const newProgress = Math.round((currentSlide / totalSlides) * 100)
      setProgress(newProgress)

      if (currentSlide <= totalSlides) {
        setConvertedSlides(DEMO_SLIDES.slice(0, currentSlide))
      }

      if (currentSlide >= totalSlides) {
        clearInterval(interval)
        setIsConverting(false)
      }
    }, 800)
  }

  const handleReset = () => {
    setConvertedSlides([])
    setProgress(0)
    setSelectedSlide(null)
    setIsConverting(false)
  }

  const handleDownload = () => {
    alert('Download functionality would be implemented here!')
  }

  return (
    <main style={{ maxWidth: '1200px', margin: '0 auto', padding: '40px 20px', minHeight: '100vh' }}>
      <header style={{ textAlign: 'center', marginBottom: '48px' }}>
        <h1 style={{ fontSize: '3rem', fontWeight: '700', marginBottom: '16px', background: 'linear-gradient(to right, #fff, #a78bfa)', WebkitBackgroundClip: 'text', WebkitTextFillColor: 'transparent', lineHeight: '1.2' }}>
          UI Component Showcase
        </h1>
        <p style={{ fontSize: '1.125rem', color: 'rgba(255,255,255,0.7)', maxWidth: '600px', margin: '0 auto' }}>
          Interactive demonstration of shadcn/ui components working together: Button, Card, and Progress
        </p>
      </header>

      <div style={{ display: 'flex', gap: '16px', justifyContent: 'center', marginBottom: '40px', flexWrap: 'wrap' }}>
        <Button onClick={handleStartConversion} disabled={isConverting} size="lg">
          {isConverting ? 'Converting...' : 'Start Conversion Demo'}
        </Button>
        <Button onClick={handleReset} variant="outline" disabled={isConverting && progress < 100}>
          Reset
        </Button>
        <Button onClick={handleDownload} variant="secondary" disabled={convertedSlides.length === 0}>
          Download All
        </Button>
      </div>

      {isConverting && (
        <Card style={{ maxWidth: '600px', margin: '0 auto 40px' }}>
          <CardHeader>
            <CardTitle>Converting Presentation</CardTitle>
            <CardDescription>
              Processing slides... {progress}% complete
            </CardDescription>
          </CardHeader>
          <CardContent>
            <Progress value={progress} />
            <div style={{ marginTop: '16px', display: 'flex', gap: '8px', flexWrap: 'wrap' }}>
              {DEMO_SLIDES.map((slide, index) => (
                <div
                  key={slide.id}
                  style={{
                    width: '40px',
                    height: '40px',
                    borderRadius: '8px',
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'center',
                    fontSize: '12px',
                    fontWeight: '600',
                    backgroundColor: index < convertedSlides.length ? '#22c55e' : '#374151',
                    color: index < convertedSlides.length ? '#fff' : '#9ca3af',
                    transition: 'all 0.3s ease'
                  }}
                >
                  {index + 1}
                </div>
              ))}
            </div>
          </CardContent>
        </Card>
      )}

      {convertedSlides.length > 0 && (
        <div style={{ marginBottom: '32px' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '24px', flexWrap: 'wrap', gap: '16px' }}>
            <h2 style={{ fontSize: '1.5rem', fontWeight: '600', color: '#fff' }}>
              Converted Slides ({convertedSlides.length})
            </h2>
            <div style={{ display: 'flex', gap: '8px' }}>
              <Button
                variant={viewMode === 'grid' ? 'default' : 'ghost'}
                size="sm"
                onClick={() => setViewMode('grid')}
              >
                Grid View
              </Button>
              <Button
                variant={viewMode === 'list' ? 'default' : 'ghost'}
                size="sm"
                onClick={() => setViewMode('list')}
              >
                List View
              </Button>
            </div>
          </div>

          {viewMode === 'grid' ? (
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(280px, 1fr))', gap: '24px' }}>
              {convertedSlides.map((slide) => (
                <Card
                  key={slide.id}
                  style={{
                    cursor: 'pointer',
                    transition: 'all 0.2s ease',
                    border: selectedSlide?.id === slide.id ? '2px solid #a78bfa' : '1px solid #374151'
                  }}
                  onClick={() => setSelectedSlide(slide)}
                >
                  <CardHeader>
                    <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
                      <div style={{
                        width: '32px',
                        height: '32px',
                        borderRadius: '8px',
                        backgroundColor: '#a78bfa',
                        display: 'flex',
                        alignItems: 'center',
                        justifyContent: 'center',
                        color: '#fff',
                        fontWeight: '600',
                        fontSize: '14px'
                      }}>
                        {slide.id}
                      </div>
                      <CardTitle style={{ fontSize: '1rem' }}>{slide.title}</CardTitle>
                    </div>
                  </CardHeader>
                  <CardContent>
                    <p style={{ color: '#9ca3af', fontSize: '14px' }}>{slide.description}</p>
                  </CardContent>
                  <CardFooter>
                    <Button variant="ghost" size="sm" style={{ width: '100%' }}>
                      View Details
                    </Button>
                  </CardFooter>
                </Card>
              ))}
            </div>
          ) : (
            <div style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
              {convertedSlides.map((slide) => (
                <Card
                  key={slide.id}
                  style={{
                    cursor: 'pointer',
                    transition: 'all 0.2s ease',
                    border: selectedSlide?.id === slide.id ? '2px solid #a78bfa' : '1px solid #374151'
                  }}
                  onClick={() => setSelectedSlide(slide)}
                >
                  <CardContent style={{ padding: '16px 24px' }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: '16px' }}>
                      <div style={{
                        width: '48px',
                        height: '48px',
                        borderRadius: '8px',
                        backgroundColor: '#a78bfa',
                        display: 'flex',
                        alignItems: 'center',
                        justifyContent: 'center',
                        color: '#fff',
                        fontWeight: '600',
                        fontSize: '18px',
                        flexShrink: 0
                      }}>
                        {slide.id}
                      </div>
                      <div style={{ flex: 1 }}>
                        <h3 style={{ fontWeight: '600', color: '#fff', marginBottom: '4px' }}>{slide.title}</h3>
                        <p style={{ color: '#9ca3af', fontSize: '14px' }}>{slide.description}</p>
                      </div>
                      <Button variant="ghost" size="sm">
                        View
                      </Button>
                    </div>
                  </CardContent>
                </Card>
              ))}
            </div>
          )}
        </div>
      )}

      {selectedSlide && (
        <Card style={{ maxWidth: '800px', margin: '0 auto' }}>
          <CardHeader>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
              <div>
                <CardTitle>Slide {selectedSlide.id}: {selectedSlide.title}</CardTitle>
                <CardDescription>{selectedSlide.description}</CardDescription>
              </div>
              <Button variant="outline" size="sm" onClick={() => setSelectedSlide(null)}>
                Close
              </Button>
            </div>
          </CardHeader>
          <CardContent>
            <div style={{
              aspectRatio: '16/9',
              backgroundColor: '#1f2937',
              borderRadius: '8px',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              marginBottom: '16px'
            }}>
              <div style={{ textAlign: 'center', color: '#9ca3af' }}>
                <div style={{ fontSize: '48px', marginBottom: '8px' }}>📊</div>
                <p>Slide Preview</p>
              </div>
            </div>
            <div style={{ display: 'flex', gap: '12px', flexWrap: 'wrap' }}>
              <Button variant="secondary" size="sm">Download Slide</Button>
              <Button variant="secondary" size="sm">Translate</Button>
              <Button variant="secondary" size="sm">Share</Button>
            </div>
          </CardContent>
        </Card>
      )}

      <div style={{ marginTop: '48px', padding: '24px', backgroundColor: 'rgba(167, 139, 250, 0.1)', borderRadius: '12px', border: '1px solid rgba(167, 139, 250, 0.2)' }}>
        <h3 style={{ fontSize: '1.125rem', fontWeight: '600', color: '#fff', marginBottom: '16px' }}>
          Component Usage Summary
        </h3>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))', gap: '16px' }}>
          <div style={{ padding: '16px', backgroundColor: 'rgba(0,0,0,0.2)', borderRadius: '8px' }}>
            <h4 style={{ fontWeight: '600', color: '#a78bfa', marginBottom: '8px' }}>Button</h4>
            <ul style={{ color: '#9ca3af', fontSize: '14px', paddingLeft: '16px' }}>
              <li>Default variant</li>
              <li>Outline variant</li>
              <li>Secondary variant</li>
              <li>Ghost variant</li>
              <li>Size variants (sm, lg)</li>
              <li>Disabled state</li>
              <li>Click handlers</li>
            </ul>
          </div>
          <div style={{ padding: '16px', backgroundColor: 'rgba(0,0,0,0.2)', borderRadius: '8px' }}>
            <h4 style={{ fontWeight: '600', color: '#a78bfa', marginBottom: '8px' }}>Card</h4>
            <ul style={{ color: '#9ca3af', fontSize: '14px', paddingLeft: '16px' }}>
              <li>Card container</li>
              <li>CardHeader</li>
              <li>CardTitle</li>
              <li>CardDescription</li>
              <li>CardContent</li>
              <li>CardFooter</li>
            </ul>
          </div>
          <div style={{ padding: '16px', backgroundColor: 'rgba(0,0,0,0.2)', borderRadius: '8px' }}>
            <h4 style={{ fontWeight: '600', color: '#a78bfa', marginBottom: '8px' }}>Progress</h4>
            <ul style={{ color: '#9ca3af', fontSize: '14px', paddingLeft: '16px' }}>
              <li>Value-based progress</li>
              <li>Animated indicator</li>
              <li>Custom styling</li>
              <li>Accessibility support</li>
            </ul>
          </div>
        </div>
      </div>
    </main>
  )
}
