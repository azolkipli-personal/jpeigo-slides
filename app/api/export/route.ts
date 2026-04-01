import { NextRequest, NextResponse } from 'next/server';
import PptxGenJS from 'pptxgenjs';

export async function POST(req: NextRequest) {
    try {
        const body = await req.json();
        const { images, language } = body as { images: Array<{ processedImageUrl?: string; url?: string }>; language?: string };

        if (!images || !Array.isArray(images) || images.length === 0) {
            return NextResponse.json({ error: 'No images provided' }, { status: 400 });
        }

        console.log('[EXPORT] Generating PPTX with', images.length, 'slides');

        const pptx = new PptxGenJS();

        for (let i = 0; i < images.length; i++) {
            const slideData = images[i];
            const slide = pptx.addSlide();

            // Try processedImageUrl first, then fall back to original url
            const imageUrl = slideData.processedImageUrl || slideData.url;
            
            if (imageUrl) {
                try {
                    const base64Data = imageUrl.split(',')[1];
                    if (!base64Data) {
                        console.warn('[EXPORT] No base64 data in image URL at index', i);
                        continue;
                    }

                    // Validate base64 length
                    if (base64Data.length < 100) {
                        console.warn('[EXPORT] Invalid base64 data at index', i);
                        continue;
                    }

                    slide.addImage({
                        data: `data:image/jpeg;base64,${base64Data}`,
                        x: 0,
                        y: 0,
                        w: '100%',
                        h: '100%'
                    });
                    console.log('[EXPORT] Added slide', i + 1, 'image');
                } catch (imgError) {
                    console.warn('[EXPORT] Failed to add image at index', i, ':', (imgError as Error).message);
                    // Add blank slide if image fails
                }
            }
        }

        pptx.author = 'PPTX Translator';
        pptx.title = 'Translated Presentation';
        pptx.subject = `Translated from ${language}`;

        const pptxResult = await pptx.write({ outputType: 'nodebuffer' });
        const pptxBuffer = pptxResult as Uint8Array;

        console.log('[EXPORT] PPTX generated, size:', pptxBuffer.byteLength);

        return new NextResponse(pptxBuffer as BodyInit, {
            headers: {
                'Content-Type': 'application/vnd.openxmlformats-officedocument.presentationml.presentation',
                'Content-Disposition': 'attachment; filename="translated-presentation.pptx"'
            }
        });

    } catch (error: any) {
        console.error('[EXPORT] ERROR:', error.message);
        console.error('[EXPORT] Stack:', error.stack);

        return NextResponse.json(
            {
                error: error.message || 'Export failed',
                details: error.toString()
            },
            { status: 500 }
        );
    }
}
