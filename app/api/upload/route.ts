
import { NextRequest, NextResponse } from 'next/server';
import ConvertAPI from 'convertapi';
import { writeFile, unlink } from 'fs/promises';
import { join } from 'path';
import { tmpdir } from 'os';


// Simple random generator if uuid not available, but usually we can just use Math.random
const generateId = () => Math.random().toString(36).substring(7);

export async function POST(req: NextRequest) {
    console.log('[UPLOAD] Request received');

    if (!process.env.CONVERT_API_SECRET) {
        console.error('[UPLOAD] Missing CONVERT_API_SECRET');
        return NextResponse.json(
            { error: 'Server configuration error: Missing CONVERT_API_SECRET' },
            { status: 500 }
        );
    }

    console.log('[UPLOAD] API Secret found, length:', process.env.CONVERT_API_SECRET.length);
    const convertapi = new ConvertAPI(process.env.CONVERT_API_SECRET);

    let tempFilePath: string | null = null;

    try {
        const formData = await req.formData();
        const file = formData.get('file') as File;

        if (!file) {
            console.error('[UPLOAD] No file in request');
            return NextResponse.json({ error: 'No file uploaded' }, { status: 400 });
        }

        console.log('[UPLOAD] File received:', file.name, 'Size:', file.size);

        // Convert file to buffer
        const arrayBuffer = await file.arrayBuffer();
        const buffer = Buffer.from(arrayBuffer);
        console.log('[UPLOAD] Buffer created, size:', buffer.length);

        // Create a temporary file
        const tempDir = tmpdir();
        const fileName = file.name || `upload-${generateId()}.pptx`;
        tempFilePath = join(tempDir, `ppt-${generateId()}-${fileName}`);

        console.log('[UPLOAD] Writing temp file to:', tempFilePath);
        await writeFile(tempFilePath, buffer);
        console.log('[UPLOAD] Temp file written successfully');

        // Convert PPTX to JPG using file path
        console.log('[UPLOAD] Starting conversion...');
        const result = await convertapi.convert('jpg', { File: tempFilePath }, 'pptx');
        console.log('[UPLOAD] Conversion successful');

        // Extract URLs
        const images = (result.response as any).Files.map((f: any) => ({
            url: f.Url,
            name: f.FileName
        }));

        console.log('[UPLOAD] Returning', images.length, 'images');
        return NextResponse.json({ images });

    } catch (error: any) {
        console.error('[UPLOAD] ERROR:', error.message);
        console.error('[UPLOAD] Error type:', error.constructor.name);
        console.error('[UPLOAD] Full error:', JSON.stringify(error, Object.getOwnPropertyNames(error), 2));

        if (error.response) {
            console.error('[UPLOAD] API Response:', error.response);
        }

        return NextResponse.json(
            {
                error: error.message || 'Conversion failed',
                errorType: error.constructor.name,
                details: error.response?.data || error.toString()
            },
            { status: 500 }
        );
    } finally {
        // Cleanup temp file
        if (tempFilePath) {
            try {
                await unlink(tempFilePath);
                console.log('[UPLOAD] Cleaned up temp file');
            } catch (ignore) {
                // Ignore cleanup errors
            }
        }
    }
}
