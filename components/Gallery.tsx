
import React from 'react';
import styles from './Gallery.module.css';

interface GalleryProps {
    images: {
        url: string;
        name?: string;
        originalText?: string;
        translatedText?: string;
        detectedLanguage?: string;
        targetLanguage?: string;
        translating?: boolean;
    }[];
}

const Gallery: React.FC<GalleryProps> = ({ images }) => {
    if (images.length === 0) return null;

    const getLanguageName = (code?: string) => {
        if (code === 'en') return 'English';
        if (code === 'ja') return 'Japanese';
        return code || 'Unknown';
    };

    return (
        <div className={styles.gallery}>
            <h2 className={styles.title}>Generated Slides ({images.length})</h2>
            <div className={styles.grid}>
                {images.map((img, index) => (
                    <div key={index} className={styles.card} style={{ animationDelay: `${index * 0.1}s` }}>
                        <div className={styles.imageWrapper}>
                            <img src={img.url} alt={`Slide ${index + 1}`} className={styles.image} loading="lazy" />
                        </div>
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
                ))}
            </div>
        </div>
    );
};

export default Gallery;
