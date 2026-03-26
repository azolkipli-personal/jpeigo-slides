'use client';

import React, { useState, useCallback } from 'react';
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
  error?: string;
  textBlocks?: Array<{
    text: string;
    boundingBox: { x: number; y: number; width: number; height: number };
    translatedText: string;
  }>;
}

interface UploadResponse {
  images: Array<{ url: string; name: string }>;
}

interface TranslateResponse {
  originalText: string;
  translatedText: string;
  detectedLanguage: string;
  targetLanguage: string;
  imageUrl: string;
  originalImageUrl?: string;
  textBlocks: Array<{
    text: string;
    boundingBox: { x: number; y: number; width: number; height: number };
    translatedText: string;
  }>;
}

export default function Home() {
  const [images, setImages] = useState<ImageWithTranslation[]>([]);
  const [loading, setLoading] = useState(false);
  const [uploadProgress, setUploadProgress] = useState(0);
  const [translateProgress, setTranslateProgress] = useState(0);
  const [error, setError] = useState<string | null>(null);

  const translateSingleImage = async (
    imageUrl: string,
    index: number
  ): Promise<ImageWithTranslation> => {
    try {
      console.log(`[TRANSLATE] Starting translation for slide ${index + 1}`);
      
      const base64Data = imageUrl.split(',')[1];
      const translationResponse = await axios.post<TranslateResponse>('/api/translate', {
        imageData: base64Data
      }, {
        timeout: 60000 // 60 second timeout
      });

      console.log(`[TRANSLATE] Completed slide ${index + 1}`);

      return {
        url: imageUrl,
        originalImageUrl: imageUrl,
        processedImageUrl: translationResponse.data.imageUrl,
        name: `Slide ${index + 1}`,
        originalText: translationResponse.data.originalText,
        translatedText: translationResponse.data.translatedText,
        detectedLanguage: translationResponse.data.detectedLanguage,
        targetLanguage: translationResponse.data.targetLanguage,
        translating: false,
        textBlocks: translationResponse.data.textBlocks
      };
    } catch (translationError) {
      const errorMessage = translationError instanceof Error 
        ? translationError.message 
        : 'Translation failed';
      
      console.error(`[TRANSLATE] Failed for slide ${index + 1}:`, errorMessage);
      
      return {
        url: imageUrl,
        originalImageUrl: imageUrl,
        name: `Slide ${index + 1}`,
        translating: false,
        error: errorMessage
      };
    }
  };

  const handleFileAccepted = useCallback(async (file: File) => {
    setLoading(true);
    setError(null);
    setImages([]);
    setUploadProgress(0);
    setTranslateProgress(0);

    try {
      console.log('[UPLOAD] Starting file upload:', file.name);

      const formData = new FormData();
      formData.append('file', file);

      // Step 1: Convert PPTX to images
      const response = await axios.post<UploadResponse>('/api/upload', formData, {
        headers: { 'Content-Type': 'multipart/form-data' },
        timeout: 120000 // 2 minute timeout for large files
      });

      console.log('[UPLOAD] Completed. Got', response.data.images.length, 'images');

      // Initialize images array with translating state
      const initialImages: ImageWithTranslation[] = response.data.images.map((img, idx) => ({
        url: img.url,
        originalImageUrl: img.url,
        name: img.name || `Slide ${idx + 1}`,
        translating: true
      }));

      setImages(initialImages);
      setUploadProgress(100);

      // Step 2: Translate each image in parallel (max 3 at a time)
      const maxConcurrent = 3;
      const totalSlides = initialImages.length;
      let completedSlides = 0;

      const processBatch = async (startIndex: number): Promise<void> => {
        const batch = initialImages.slice(startIndex, startIndex + maxConcurrent);
        
        if (batch.length === 0) return;

        const results = await Promise.all(
          batch.map((_, offset) => 
            translateSingleImage(initialImages[startIndex + offset].url, startIndex + offset)
          )
        );

        // Update state with results
        setImages(prev => {
          const newImages = [...prev];
          results.forEach((result, idx) => {
            newImages[startIndex + idx] = result;
          });
          return newImages;
        });

        completedSlides += results.length;
        setTranslateProgress(Math.round((completedSlides / totalSlides) * 100));

        // Process next batch
        if (startIndex + maxConcurrent < totalSlides) {
          await processBatch(startIndex + maxConcurrent);
        }
      };

      await processBatch(0);
      console.log('[TRANSLATE] All slides processed');

    } catch (err) {
      console.error('[ERROR]', err);
      
      if (axios.isAxiosError(err)) {
        const status = err.response?.status;
        const message = err.response?.data?.error || err.message;
        
        if (status === 500) {
          setError(`Server error: ${message}. Make sure LibreOffice is installed.`);
        } else if (status === 413) {
          setError('File too large. Please upload a smaller PPTX file.');
        } else {
          setError(`Upload failed: ${message}`);
        }
      } else {
        setError('Failed to process file. Please try again.');
      }
    } finally {
      setLoading(false);
    }
  }, []);

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
        responseType: 'blob',
        timeout: 60000
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

  const handleRetry = (index: number) => {
    const image = images[index];
    if (!image.originalImageUrl) return;

    setImages(prev => prev.map((img, idx) => 
      idx === index ? { ...img, translating: true, error: undefined } : img
    ));

    translateSingleImage(image.originalImageUrl, index).then(result => {
      setImages(prev => prev.map((img, idx) => 
        idx === index ? result : img
      ));
    });
  };

  const completedCount = images.filter(img => img.processedImageUrl).length;
  const hasErrors = images.some(img => img.error);

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

        {(loading || uploadProgress > 0 || translateProgress > 0) && (
          <div style={{
            marginTop: '24px',
            padding: '20px',
            background: 'rgba(139, 92, 246, 0.1)',
            border: '1px solid rgba(139, 92, 246, 0.2)',
            borderRadius: '12px',
            color: '#c4b5fd'
          }}>
            {uploadProgress > 0 && uploadProgress < 100 && (
              <div style={{ marginBottom: '16px' }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '8px' }}>
                  <span>Converting PPTX to images...</span>
                  <span>{uploadProgress}%</span>
                </div>
                <div style={{
                  height: '8px',
                  background: 'rgba(139, 92, 246, 0.2)',
                  borderRadius: '4px',
                  overflow: 'hidden'
                }}>
                  <div style={{
                    width: `${uploadProgress}%`,
                    height: '100%',
                    background: 'linear-gradient(90deg, #8b5cf6, #a78bfa)',
                    transition: 'width 0.3s ease'
                  }} />
                </div>
              </div>
            )}

            {translateProgress > 0 && (
              <div>
                <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '8px' }}>
                  <span>
                    {translateProgress < 100 
                      ? `Translating slides (${completedCount}/${images.length})...`
                      : 'Translation complete!'}
                  </span>
                  <span>{translateProgress}%</span>
                </div>
                <div style={{
                  height: '8px',
                  background: 'rgba(139, 92, 246, 0.2)',
                  borderRadius: '4px',
                  overflow: 'hidden'
                }}>
                  <div style={{
                    width: `${translateProgress}%`,
                    height: '100%',
                    background: 'linear-gradient(90deg, #22c55e, #4ade80)',
                    transition: 'width 0.3s ease'
                  }} />
                </div>
              </div>
            )}
          </div>
        )}

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

        {hasErrors && (
          <div style={{
            marginTop: '24px',
            padding: '16px',
            background: 'rgba(234, 179, 8, 0.1)',
            border: '1px solid rgba(234, 179, 8, 0.2)',
            borderRadius: '12px',
            color: '#fde047',
            textAlign: 'center'
          }}>
            Some slides failed to translate. You can retry individual slides.
          </div>
        )}

        {completedCount > 0 && completedCount === images.length && (
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

      <Gallery images={images} onRetry={handleRetry} />

      <style jsx global>{`
        @keyframes fadeInDown {
          from { opacity: 0; transform: translateY(-30px); }
          to { opacity: 1; transform: translateY(0); }
        }
        @keyframes fadeInUp {
          from { opacity: 0; transform: translateY(30px); }
          to { opacity: 1; transform: translateY(0); }
        }
        @keyframes fadeIn {
          from { opacity: 0; }
          to { opacity: 1; }
        }
      `}</style>
    </main>
  );
}
