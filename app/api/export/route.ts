import { NextRequest, NextResponse } from 'next/server';
import PptxGenJS from 'pptxgenjs';

export async function POST(req: NextRequest) {
    try {
        const body = await req.json();
        const { images, language } = body as { images: Array<{ processedImageUrl?: string }>; language?: string };

        if (!images || !Array.isArray(images) || images.length === 0) {
            return NextResponse.json({ error: 'No images provided' }, { status: 400 });
        }

        console.log('[EXPORT] Generating PPTX with', images.length, 'slides');

        const pptx = new PptxGenJS();

        for (let i = 0; i < images.length; i++) {
            const slideData = images[i];
            const slide = pptx.addSlide();

            if (slideData.processedImageUrl) {
                const base64Data = slideData.processedImageUrl.split(',')[1];

                slide.addImage({
                    data: `data:image/jpeg;base64,${base64Data}`,
                    x: 0,
                    y: 0,
                    w: '100%',
                    h: '100%'
                });
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
