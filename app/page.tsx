'use client';

import React, { useState } from 'react';
import axios from 'axios';
import Dropzone from '@/components/Dropzone';
import Gallery from '@/components/Gallery';

interface ImageWithTranslation {
  url: string;
  originalImageUrl?: string;
  processedImageUrl?: string;
  name?: string;
  originalText?: string;
  translatedText?: string;
  detectedLanguage?: string;
  targetLanguage?: string;
  translating?: boolean;
  textBlocks?: Array<{
    text: string;
    boundingBox: { x: number; y: number; width: number; height: number };
    translatedText: string;
  }>;
}

export default function Home() {
  const [images, setImages] = useState<ImageWithTranslation[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleFileAccepted = async (file: File) => {
    setLoading(true);
    setError(null);
    setImages([]);

    const formData = new FormData();
    formData.append('file', file);

    try {
      // Step 1: Convert PPTX to images
      const response = await axios.post('/api/upload', formData, {
        headers: { 'Content-Type': 'multipart/form-data' },
      });

      const convertedImages: ImageWithTranslation[] = response.data.images.map((img: ImageWithTranslation) => ({
        ...img,
        originalImageUrl: img.url,
        translating: true
      }));

      setImages(convertedImages);
      setLoading(false);

      // Step 2: Translate each image (with text replacement)
      for (let i = 0; i < convertedImages.length; i++) {
        try {
          const base64Data = convertedImages[i].url.split(',')[1];
          const translationResponse = await axios.post('/api/translate', {
            imageData: base64Data
          });

          setImages(prev => prev.map((img, index) =>
            index === i
              ? {
                  ...img,
                  originalText: translationResponse.data.originalText,
                  translatedText: translationResponse.data.translatedText,
                  detectedLanguage: translationResponse.data.detectedLanguage,
                  targetLanguage: translationResponse.data.targetLanguage,
                  originalImageUrl: translationResponse.data.originalImageUrl,
                  processedImageUrl: translationResponse.data.imageUrl,
                  textBlocks: translationResponse.data.textBlocks,
                  translating: false
                }
              : img
          ));
        } catch (translationError) {
          console.error(`Translation failed for image ${i}:`, translationError);
          setImages(prev => prev.map((img, index) =>
            index === i ? { ...img, translating: false } : img
          ));
        }
      }

    } catch (err) {
      console.error(err);
      setError('Failed to convert presentation. Please check your file.');
      setLoading(false);
    }
  };

  const handleExportPPTX = async () => {
    try {
      const processedImages = images.filter(img => img.processedImageUrl);
      if (processedImages.length === 0) {
        setError('No processed images to export');
        return;
      }

      const dominantLanguage = images[0]?.detectedLanguage || 'en';

      const response = await axios.post('/api/export', {
        images: processedImages,
        language: dominantLanguage
      }, {
        responseType: 'blob'
      });

      const url = window.URL.createObjectURL(new Blob([response.data]));
      const link = document.createElement('a');
      link.href = url;
      link.setAttribute('download', 'translated-presentation.pptx');
      document.body.appendChild(link);
      link.click();
      link.remove();
      window.URL.revokeObjectURL(url);

    } catch (err) {
      console.error('Export failed:', err);
      setError('Failed to export PPTX');
    }
  };

  return (
    <main style={{ maxWidth: '1200px', margin: '0 auto', padding: '60px 20px', minHeight: '100vh' }}>
      <header style={{ textAlign: 'center', marginBottom: '80px', animation: 'fadeInDown 0.8s ease-out' }}>
        <h1 style={{
          fontSize: '4rem',
          fontWeight: 700,
          marginBottom: '24px',
          background: 'linear-gradient(to right, #fff, #a78bfa)',
          WebkitBackgroundClip: 'text',
          WebkitTextFillColor: 'transparent',
          lineHeight: 1.1
        }}>
          PPTX Translator
        </h1>
        <p style={{ fontSize: '1.25rem', color: 'rgba(255,255,255,0.7)', maxWidth: '600px', margin: '0 auto' }}>
          Convert PowerPoint slides to images and automatically translate between English and Japanese.
        </p>
      </header>

      <div style={{ maxWidth: '800px', margin: '0 auto', animation: 'fadeInUp 0.8s 0.2s ease-out backwards' }}>
        <Dropzone onFileAccepted={handleFileAccepted} isLoading={loading} />

        {error && (
          <div style={{
            marginTop: '24px',
            padding: '16px',
            background: 'rgba(239, 68, 68, 0.1)',
            border: '1px solid rgba(239, 68, 68, 0.2)',
            borderRadius: '12px',
            color: '#fca5a5',
            textAlign: 'center',
            animation: 'fadeIn 0.3s ease'
          }}>
            {error}
          </div>
        )}

        {images.length > 0 && images[0]?.processedImageUrl && (
          <button
            onClick={handleExportPPTX}
            style={{
              display: 'block',
              width: '100%',
              maxWidth: '400px',
              margin: '24px auto 0',
              padding: '16px 32px',
              fontSize: '1.1rem',
              fontWeight: 600,
              color: '#fff',
              background: 'linear-gradient(135deg, #8b5cf6 0%, #6366f1 100%)',
              border: 'none',
              borderRadius: '12px',
              cursor: 'pointer',
              transition: 'transform 0.2s ease, box-shadow 0.2s ease',
              boxShadow: '0 4px 14px 0 rgba(139, 92, 246, 0.39)'
            }}
            onMouseOver={(e) => {
              e.currentTarget.style.transform = 'translateY(-2px)';
              e.currentTarget.style.boxShadow = '0 6px 20px 0 rgba(139, 92, 246, 0.5)';
            }}
            onMouseOut={(e) => {
              e.currentTarget.style.transform = 'translateY(0)';
              e.currentTarget.style.boxShadow = '0 4px 14px 0 rgba(139, 92, 246, 0.39)';
            }}
          >
            Download Translated PPTX
          </button>
        )}
      </div>

      <Gallery images={images} />

      <style jsx global>{`
        @keyframes fadeInDown {
          from { opacity: 0; transform: translateY(-30px); }
          to { opacity: 1; transform: translateY(0); }
        }
        @keyframes fadeInUp {
          from { opacity: 0; transform: translateY(30px); }
          to { opacity: 1; transform: translateY(0); }
        }
      `}</style>
    </main>
  );
}
