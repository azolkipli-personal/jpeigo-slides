
import React, { useState } from 'react';
import styles from './Gallery.module.css';

interface GalleryProps {
    images: {
        url: string;
        originalImageUrl?: string;
        processedImageUrl?: string;
        name?: string;
        originalText?: string;
        translatedText?: string;
        detectedLanguage?: string;
        targetLanguage?: string;
        translating?: boolean;
    }[];
}

const Gallery: React.FC<GalleryProps> = ({ images }) => {
    const [showProcessed, setShowProcessed] = useState<{ [key: number]: boolean }>({});

    if (images.length === 0) return null;

    const getLanguageName = (code?: string) => {
        if (code === 'en') return 'English';
        if (code === 'ja') return 'Japanese';
        return code || 'Unknown';
    };

    const toggleView = (index: number) => {
        setShowProcessed(prev => ({ ...prev, [index]: !prev[index] }));
    };

    return (
        <div className={styles.gallery}>
            <h2 className={styles.title}>Generated Slides ({images.length})</h2>
            <div className={styles.grid}>
                {images.map((img, index) => {
                    const displayProcessed = showProcessed[index] && img.processedImageUrl;
                    const displayImage = displayProcessed ? img.processedImageUrl : (img.originalImageUrl || img.url);

                    return (
                        <div key={index} className={styles.card} style={{ animationDelay: `${index * 0.1}s` }}>
                            <div className={styles.imageWrapper}>
                                <img src={displayImage || img.url} alt={`Slide ${index + 1}`} className={styles.image} loading="lazy" />
                            </div>

                            {img.processedImageUrl && (
                                <button
                                    onClick={() => toggleView(index)}
                                    style={{
                                        display: 'block',
                                        width: '100%',
                                        padding: '8px 16px',
                                        marginTop: '8px',
                                        fontSize: '0.8rem',
                                        fontWeight: 500,
                                        color: '#fff',
                                        background: displayProcessed
                                            ? 'rgba(34, 197, 94, 0.2)'
                                            : 'rgba(139, 92, 246, 0.2)',
                                        border: displayProcessed
                                            ? '1px solid rgba(34, 197, 94, 0.3)'
                                            : '1px solid rgba(139, 92, 246, 0.3)',
                                        borderRadius: '6px',
                                        cursor: 'pointer',
                                        transition: 'all 0.2s ease'
                                    }}
                                >
                                    {displayProcessed ? '✓ Showing Translated' : 'Show Translated'}
                                </button>
                            )}

                            <div className={styles.caption}>Slide {index + 1}</div>

                            {img.translating && (
                                <div style={{
                                    padding: '12px',
                                    background: 'rgba(167, 139, 250, 0.1)',
                                    borderRadius: '8px',
                                    marginTop: '12px',
                                    textAlign: 'center',
                                    color: '#a78bfa'
                                }}>
                                    <div style={{ fontSize: '0.875rem' }}>Translating...</div>
                                </div>
                            )}

                            {!img.translating && img.translatedText && (
                                <div style={{
                                    marginTop: '12px',
                                    padding: '12px',
                                    background: 'rgba(255, 255, 255, 0.05)',
                                    borderRadius: '8px',
                                    fontSize: '0.875rem'
                                }}>
                                    <div style={{
                                        display: 'flex',
                                        justifyContent: 'space-between',
                                        marginBottom: '8px',
                                        fontSize: '0.75rem',
                                        color: 'rgba(255, 255, 255, 0.5)',
                                        textTransform: 'uppercase',
                                        letterSpacing: '0.05em'
                                    }}>
                                        <span>{getLanguageName(img.detectedLanguage)}</span>
                                        <span>→</span>
                                        <span>{getLanguageName(img.targetLanguage)}</span>
                                    </div>
                                    <div style={{
                                        padding: '8px',
                                        background: 'rgba(0, 0, 0, 0.2)',
                                        borderRadius: '4px',
                                        color: 'rgba(255, 255, 255, 0.9)',
                                        lineHeight: 1.6,
                                        whiteSpace: 'pre-wrap',
                                        wordBreak: 'break-word'
                                    }}>
                                        {img.translatedText}
                                    </div>
                                </div>
                            )}

                            {!img.translating && !img.translatedText && img.originalText === '' && (
                                <div style={{
                                    marginTop: '12px',
                                    padding: '12px',
                                    background: 'rgba(255, 255, 255, 0.05)',
                                    borderRadius: '8px',
                                    fontSize: '0.875rem',
                                    color: 'rgba(255, 255, 255, 0.5)',
                                    textAlign: 'center'
                                }}>
                                    No text detected
                                </div>
                            )}
                        </div>
                    );
                })}
            </div>
        </div>
    );
};

export default Gallery;
