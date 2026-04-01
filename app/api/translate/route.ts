import { NextRequest, NextResponse } from 'next/server';
import { removeTextWithFill, overlayText, getLanguage, detectTargetLanguage, TextBlockWithTranslation, TextBlock } from '@/lib/imageProcessing';
import { writeFile, unlink } from 'fs/promises';
import { tmpdir } from 'os';
import { join } from 'path';
import axios from 'axios';
import sharp from 'sharp';

const LIBRETRANSLATE_URL = process.env.LIBRETRANSLATE_URL;

async function translateWithLibreTranslate(text: string, targetLang: string): Promise<string> {
    if (!LIBRETRANSLATE_URL) {
        throw new Error('LibreTranslate not configured');
    }
    try {
        const response = await axios.post(`${LIBRETRANSLATE_URL}/translate`, {
            q: text,
            source: 'auto',
            target: targetLang
        }, { timeout: 15000 });
        return response.data.translatedText || text;
    } catch (error) {
        console.error('[TRANSLATE] LibreTranslate error:', (error as Error).message);
        throw error;
    }
}

async function translateWithGoogleCloud(text: string, apiKey: string, targetLang: string): Promise<string> {
    try {
        const response = await axios.post(
            `https://translation.googleapis.com/language/translate/v2?key=${apiKey}`,
            { q: [text], target: targetLang, format: 'text' },
            { timeout: 10000 }
        );
        return response.data.data?.translations?.[0]?.translatedText || text;
    } catch (error) {
        console.error('[TRANSLATE] Google Translate error:', (error as Error).message);
        throw error;
    }
}

interface VisionBlock {
    paragraphs?: Array<{
        boundingBox?: { vertices?: Array<{ x?: number; y?: number }> };
        words?: Array<{
            symbols?: Array<{ text?: string }>;
        }>;
    }>;
    confidence?: number;
}

export async function POST(req: NextRequest) {
    console.log('[TRANSLATE] Request received');

    let tempImagePath: string | null = null;
    let tempOutputPath: string | null = null;
    const googleApiKey = process.env.GOOGLE_CLOUD_API_KEY;
    const useGoogleCloud = !!googleApiKey && googleApiKey.length > 10;

    try {
        const { imageUrl, imageData } = await req.json();

        if (!imageUrl && !imageData) {
            return NextResponse.json({ error: 'No image provided' }, { status: 400 });
        }

        console.log('[TRANSLATE] Processing image...');

        const tempDir = tmpdir();
        const imageId = Math.random().toString(36).substring(7);
        tempImagePath = join(tempDir, `slide-${imageId}.jpg`);
        tempOutputPath = join(tempDir, `slide-processed-${imageId}.jpg`);

        // Write the input image
        if (imageData) {
            const buffer = Buffer.from(imageData, 'base64');
            await writeFile(tempImagePath, buffer);
        } else if (imageUrl && imageUrl.startsWith('data:image')) {
            const base64Data = imageUrl.split(',')[1];
            const buffer = Buffer.from(base64Data, 'base64');
            await writeFile(tempImagePath, buffer);
        }

        // Convert to consistent JPEG format using sharp
        try {
            await sharp(tempImagePath)
                .jpeg({ quality: 90 })
                .toFile(tempOutputPath);
            console.log('[TRANSLATE] Image normalized to JPEG');
        } catch (sharpError) {
            console.warn('[TRANSLATE] Sharp normalization failed, using original:', (sharpError as Error).message);
            // Copy original to output path
            const fs = require('fs');
            fs.copyFileSync(tempImagePath, tempOutputPath);
        }

        console.log('[TRANSLATE] Extracting text with Google Cloud Vision API...');

        let textBlocks: TextBlock[] = [];
        let fullText = '';

        // Use Google Cloud Vision API
        if (useGoogleCloud) {
            try {
                // Read the normalized image for Vision API
                const imageBuffer = await sharp(tempOutputPath).toBuffer();
                const base64Image = imageBuffer.toString('base64');

                const visionResponse = await axios.post(
                    `https://vision.googleapis.com/v1/images:annotate?key=${googleApiKey}`,
                    { 
                        requests: [{ 
                            image: { content: base64Image }, 
                            features: [{ type: 'DOCUMENT_TEXT_DETECTION' }] 
                        }] 
                    },
                    { timeout: 30000 }
                );

                const fullTextAnnotation = visionResponse.data.responses[0]?.fullTextAnnotation;
                
                if (fullTextAnnotation?.pages) {
                    fullTextAnnotation.pages.forEach((page: any) => {
                        page.blocks?.forEach((block: VisionBlock) => {
                            block.paragraphs?.forEach((paragraph) => {
                                let paragraphText = '';
                                const vertices = paragraph.boundingBox?.vertices;

                                if (vertices && vertices.length >= 4) {
                                    const minX = Math.min(...vertices.map((v: any) => v.x || 0));
                                    const maxX = Math.max(...vertices.map((v: any) => v.x || 0));
                                    const minY = Math.min(...vertices.map((v: any) => v.y || 0));
                                    const maxY = Math.max(...vertices.map((v: any) => v.y || 0));

                                    paragraph.words?.forEach((word) => {
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
                console.error('[TRANSLATE] Google Vision failed:', (visionError as Error).message);
                return NextResponse.json({ 
                    error: 'OCR failed. Please try again.',
                    details: (visionError as Error).message
                }, { status: 500 });
            }
        } else {
            return NextResponse.json({ 
                error: 'No OCR service configured',
                hint: 'Add GOOGLE_CLOUD_API_KEY to .env.local for OCR'
            }, { status: 500 });
        }

        if (textBlocks.length === 0) {
            console.log('[TRANSLATE] No text detected in image');
            // Return original image even if no text detected
            const originalImageBuffer = await sharp(tempOutputPath).toBuffer();
            const originalImageBase64 = originalImageBuffer.toString('base64');
            return NextResponse.json({
                originalText: '',
                translatedText: '',
                detectedLanguage: 'unknown',
                message: 'No text detected in image',
                imageUrl: `data:image/jpeg;base64,${originalImageBase64}`,
                originalImageUrl: imageUrl || imageData,
                textBlocks: []
            });
        }

        console.log('[TRANSLATE] Found', textBlocks.length, 'text block(s)');

        const detectedLanguage = getLanguage(fullText);
        const targetLanguage = detectTargetLanguage(detectedLanguage);
        console.log('[TRANSLATE] Detected:', detectedLanguage, '→ Target:', targetLanguage);

        console.log('[TRANSLATE] Translating text...');
        const textBlocksWithTranslation: TextBlockWithTranslation[] = [];

        for (const block of textBlocks) {
            let translation = block.text;

            try {
                if (useGoogleCloud) {
                    console.log('[TRANSLATE] Using Google Cloud Translation...');
                    translation = await translateWithGoogleCloud(block.text, googleApiKey!, targetLanguage);
                } else if (LIBRETRANSLATE_URL) {
                    console.log('[TRANSLATE] Using LibreTranslate...');
                    translation = await translateWithLibreTranslate(block.text, targetLanguage);
                } else {
                    console.log('[TRANSLATE] No translation service configured, keeping original text');
                }
            } catch (translateError) {
                console.warn('[TRANSLATE] Translation service failed, keeping original text');
                translation = block.text;
            }

            textBlocksWithTranslation.push({ ...block, translatedText: translation });
        }

        console.log('[TRANSLATE] Processing images...');
        
        // Initialize with original image in case processing fails
        let processedImageUrl = `data:image/jpeg;base64,${(await sharp(tempOutputPath).toBuffer()).toString('base64')}`;
         
        try {
            const boundingBoxes = textBlocks.map(b => b.boundingBox);
            const cleanedImageBuffer = await removeTextWithFill(tempOutputPath, boundingBoxes);
            const processedImageBuffer = await overlayText(cleanedImageBuffer, textBlocksWithTranslation, targetLanguage);
            processedImageUrl = `data:image/jpeg;base64,${processedImageBuffer.toString('base64')}`;
            console.log('[TRANSLATE] Image processing complete');
        } catch (imageError) {
            console.warn('[TRANSLATE] Image processing failed, returning original:', (imageError as Error).message);
            // processedImageUrl already contains the original image
        }

        const translatedText = textBlocksWithTranslation.map(b => b.translatedText).join('\n\n');
        console.log('[TRANSLATE] Complete!');

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
        return NextResponse.json({ 
            error: (error as Error).message || 'Translation failed',
            hint: 'Try using a clearer image with readable text'
        }, { status: 500 });
    } finally {
        if (tempImagePath) {
            try { await unlink(tempImagePath); } catch { }
        }
        if (tempOutputPath) {
            try { await unlink(tempOutputPath); } catch { }
        }
    }
}
