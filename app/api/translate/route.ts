import { NextRequest, NextResponse } from 'next/server';
import { removeTextWithFill, overlayText, getLanguage, detectTargetLanguage, TextBlockWithTranslation, TextBlock } from '@/lib/imageProcessing';
import { writeFile, unlink } from 'fs/promises';
import { tmpdir } from 'os';
import { join } from 'path';
import axios from 'axios';
import Tesseract from 'tesseract.js';

const LIBRETRANSLATE_URL = process.env.LIBRETRANSLATE_URL || 'https://libretranslate.com';

async function translateWithLibreTranslate(text: string, targetLang: string): Promise<string> {
    try {
        const response = await axios.post(`${LIBRETRANSLATE_URL}/translate`, {
            q: text,
            source: 'auto',
            target: targetLang
        }, { timeout: 15000 });
        return response.data.translatedText;
    } catch (error) {
        console.error('[TRANSLATE] LibreTranslate error:', (error as Error).message);
        throw error;
    }
}

export async function POST(req: NextRequest) {
    console.log('[TRANSLATE] Request received');

    let tempImagePath: string | null = null;
    const apiKey = process.env.GOOGLE_CLOUD_API_KEY;
    const useGoogleCloud = !!apiKey;

    try {
        const { imageUrl, imageData } = await req.json();

        if (!imageUrl && !imageData) {
            return NextResponse.json({ error: 'No image provided' }, { status: 400 });
        }

        console.log('[TRANSLATE] Processing image...');

        const tempDir = tmpdir();
        const imageId = Math.random().toString(36).substring(7);
        tempImagePath = join(tempDir, `slide-${imageId}.jpg`);

        if (imageData) {
            const buffer = Buffer.from(imageData, 'base64');
            await writeFile(tempImagePath, buffer);
        } else if (imageUrl && imageUrl.startsWith('data:image')) {
            const base64Data = imageUrl.split(',')[1];
            const buffer = Buffer.from(base64Data, 'base64');
            await writeFile(tempImagePath, buffer);
        }

        console.log('[TRANSLATE] Extracting text...');

        let textBlocks: TextBlock[] = [];
        let fullText = '';

        // Try Tesseract.js (local OCR, no API key)
        try {
            console.log('[TRANSLATE] Using Tesseract.js for OCR (local, free)...');
            const result = await Tesseract.recognize(tempImagePath, 'eng', {
                logger: (m) => {
                    if (m.status === 'recognizing text') {
                        console.log(`[TRANSLATE] OCR progress: ${Math.round(m.progress * 100)}%`);
                    }
                }
            });

            fullText = result.data.text.trim();
            if (fullText) {
                textBlocks.push({
                    text: fullText,
                    boundingBox: { x: 50, y: 50, width: 800, height: 100 },
                    confidence: result.data.confidence / 100
                });
                console.log('[TRANSLATE] Tesseract extracted', fullText.length, 'characters');
            }
        } catch (tesseractError) {
            console.warn('[TRANSLATE] Tesseract failed:', (tesseractError as Error).message);
        }

        // If Tesseract failed, try Google Cloud Vision API
        if (textBlocks.length === 0 && useGoogleCloud) {
            try {
                console.log('[TRANSLATE] Trying Google Cloud Vision API...');
                const visionResponse = await axios.post(
                    `https://vision.googleapis.com/v1/images:annotate?key=${apiKey}`,
                    { requests: [{ image: { content: imageData }, features: [{ type: 'DOCUMENT_TEXT_DETECTION' }] }] },
                    { timeout: 30000 }
                );
                const fullTextAnnotation = visionResponse.data.responses[0]?.fullTextAnnotation;
                
                if (fullTextAnnotation?.pages) {
                    fullTextAnnotation.pages.forEach((page: any) => {
                        page.blocks?.forEach((block: any) => {
                            block.paragraphs?.forEach((paragraph: any) => {
                                let paragraphText = '';
                                const vertices = paragraph.boundingBox?.vertices;

                                if (vertices && vertices.length >= 4) {
                                    const minX = Math.min(...vertices.map((v: any) => v.x || 0));
                                    const maxX = Math.max(...vertices.map((v: any) => v.x || 0));
                                    const minY = Math.min(...vertices.map((v: any) => v.y || 0));
                                    const maxY = Math.max(...vertices.map((v: any) => v.y || 0));

                                    paragraph.words?.forEach((word: any) => {
                                        word.symbols?.forEach((symbol: any) => {
                                            paragraphText += symbol.text || '';
                                            fullText += symbol.text || '';
                                        });
                                    });

                                    if (paragraphText.trim()) {
                                        textBlocks.push({
                                            text: paragraphText,
                                            boundingBox: { x: minX, y: minY, width: maxX - minX, height: maxY - minY },
                                            confidence: block.confidence || 0.9
                                        });
                                    }
                                }
                            });
                        });
                    });
                    console.log('[TRANSLATE] Google Cloud Vision API successful');
                }
            } catch (visionError) {
                console.warn('[TRANSLATE] Google Cloud Vision failed:', (visionError as Error).message);
            }
        }

        if (textBlocks.length === 0) {
            console.log('[TRANSLATE] No text detected');
            return NextResponse.json({
                originalText: '',
                translatedText: '',
                detectedLanguage: 'unknown',
                message: 'No text detected in image',
                imageUrl: imageUrl || imageData
            });
        }

        console.log('[TRANSLATE] Found', textBlocks.length, 'text blocks');

        const detectedLanguage = getLanguage(fullText);
        const targetLanguage = detectTargetLanguage(detectedLanguage);
        console.log('[TRANSLATE] Detected:', detectedLanguage, '→ Target:', targetLanguage);

        console.log('[TRANSLATE] Translating...');
        const textBlocksWithTranslation: TextBlockWithTranslation[] = [];

        for (const block of textBlocks) {
            try {
                let translation: string;
                if (useGoogleCloud) {
                    const response = await axios.post(
                        `https://translation.googleapis.com/language/translate/v2?key=${apiKey}`,
                        { q: [block.text], target: targetLanguage, format: 'text' },
                        { timeout: 10000 }
                    );
                    translation = response.data.data.translations[0].translatedText;
                } else {
                    translation = await translateWithLibreTranslate(block.text, targetLanguage);
                }
                textBlocksWithTranslation.push({ ...block, translatedText: translation });
            } catch (translateError) {
                console.warn('[TRANSLATE] Translation failed, keeping original');
                textBlocksWithTranslation.push({ ...block, translatedText: block.text });
            }
        }

        console.log('[TRANSLATE] Processing images...');
        const boundingBoxes = textBlocks.map(b => b.boundingBox);
        const cleanedImageBuffer = await removeTextWithFill(tempImagePath, boundingBoxes);
        const processedImageBuffer = await overlayText(cleanedImageBuffer, textBlocksWithTranslation, targetLanguage);

        const processedImageBase64 = processedImageBuffer.toString('base64');
        const processedImageUrl = `data:image/jpeg;base64,${processedImageBase64}`;

        const translatedText = textBlocksWithTranslation.map(b => b.translatedText).join('\n\n');
        console.log('[TRANSLATE] Complete');

        return NextResponse.json({
            originalText: fullText,
            translatedText: translatedText,
            detectedLanguage: detectedLanguage,
            targetLanguage: targetLanguage,
            imageUrl: processedImageUrl,
            originalImageUrl: imageUrl || imageData,
            textBlocks: textBlocks.map((b, i) => ({
                text: b.text,
                boundingBox: b.boundingBox,
                translatedText: textBlocksWithTranslation[i]?.translatedText || ''
            }))
        });

    } catch (error) {
        console.error('[TRANSLATE] ERROR:', (error as Error).message);
        return NextResponse.json({ error: (error as Error).message || 'Translation failed' }, { status: 500 });
    } finally {
        if (tempImagePath) {
            try { await unlink(tempImagePath); } catch { }
        }
    }
}
