
import { NextRequest, NextResponse } from 'next/server';
import vision from '@google-cloud/vision';
import { Translate } from '@google-cloud/translate/build/src/v2';

export async function POST(req: NextRequest) {
    console.log('[TRANSLATE] Request received');

    if (!process.env.GOOGLE_CLOUD_API_KEY) {
        console.error('[TRANSLATE] Missing GOOGLE_CLOUD_API_KEY');
        return NextResponse.json(
            { error: 'Server configuration error: Missing GOOGLE_CLOUD_API_KEY' },
            { status: 500 }
        );
    }

    try {
        const { imageUrl } = await req.json();

        if (!imageUrl) {
            return NextResponse.json({ error: 'No image URL provided' }, { status: 400 });
        }

        console.log('[TRANSLATE] Processing image:', imageUrl);

        // Initialize Google Cloud clients with API key
        const visionClient = new vision.ImageAnnotatorClient({
            apiKey: process.env.GOOGLE_CLOUD_API_KEY
        });

        const translateClient = new Translate({
            key: process.env.GOOGLE_CLOUD_API_KEY
        });

        // Extract text from image using OCR
        console.log('[TRANSLATE] Extracting text with OCR...');
        const [result] = await visionClient.textDetection(imageUrl);
        const detections = result.textAnnotations;

        if (!detections || detections.length === 0) {
            console.log('[TRANSLATE] No text detected in image');
            return NextResponse.json({
                originalText: '',
                translatedText: '',
                detectedLanguage: 'unknown',
                message: 'No text detected in image'
            });
        }

        const extractedText = detections[0].description || '';
        console.log('[TRANSLATE] Extracted text length:', extractedText.length);

        // Detect language
        console.log('[TRANSLATE] Detecting language...');
        const [detection] = await translateClient.detect(extractedText);
        const detectedLanguage = detection.language;
        console.log('[TRANSLATE] Detected language:', detectedLanguage);

        // Determine target language (EN ↔ JA)
        let targetLanguage: string;
        if (detectedLanguage === 'ja') {
            targetLanguage = 'en';
        } else if (detectedLanguage === 'en') {
            targetLanguage = 'ja';
        } else {
            // Default: translate to English if language is neither EN nor JA
            targetLanguage = 'en';
        }

        console.log('[TRANSLATE] Translating to:', targetLanguage);

        // Translate text
        const [translation] = await translateClient.translate(extractedText, targetLanguage);
        console.log('[TRANSLATE] Translation complete');

        return NextResponse.json({
            originalText: extractedText,
            translatedText: translation,
            detectedLanguage: detectedLanguage,
            targetLanguage: targetLanguage
        });

    } catch (error: any) {
        console.error('[TRANSLATE] ERROR:', error.message);
        console.error('[TRANSLATE] Stack:', error.stack);

        return NextResponse.json(
            {
                error: error.message || 'Translation failed',
                details: error.toString()
            },
            { status: 500 }
        );
    }
}
