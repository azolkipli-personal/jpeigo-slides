
import { NextRequest, NextResponse } from 'next/server';
import { writeFile, unlink, mkdir, readdir, readFile } from 'fs/promises';
import { join } from 'path';
import { tmpdir } from 'os';
import { exec } from 'child_process';
import { promisify } from 'util';

const execAsync = promisify(exec);

// Simple random generator if uuid not available, but usually we can just use Math.random
const generateId = () => Math.random().toString(36).substring(7);

export async function POST(req: NextRequest) {
    console.log('[UPLOAD] Request received');

    let tempFilePath: string | null = null;
    let outputDir: string | null = null;

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
        outputDir = join(tempDir, `slides-${generateId()}`);

        console.log('[UPLOAD] Writing temp file to:', tempFilePath);
        await writeFile(tempFilePath, buffer);
        console.log('[UPLOAD] Temp file written successfully');

        // Create output directory
        await mkdir(outputDir, { recursive: true });
        console.log('[UPLOAD] Output directory created:', outputDir);

        // Convert PPTX to JPG using LibreOffice
        console.log('[UPLOAD] Starting LibreOffice conversion...');
        
        let libreofficePath = '';
        if (process.platform === 'win32') {
            // Try common Windows paths
            const possiblePaths = [
                'C:\\Program Files\\LibreOffice\\program\\soffice.exe',
                'C:\\Program Files (x86)\\LibreOffice\\program\\soffice.exe',
                `${process.env.PROGRAMFILES}\\LibreOffice\\program\\soffice.exe`,
                `${process.env['PROGRAMFILES(X86)']}\\LibreOffice\\program\\soffice.exe`
            ];
            for (const path of possiblePaths) {
                try {
                    const { existsSync } = require('fs');
                    if (existsSync(path)) {
                        libreofficePath = path;
                        break;
                    }
                } catch {
                    // Continue checking other paths
                }
            }
            if (!libreofficePath) {
                console.error('[UPLOAD] LibreOffice not found. Please install LibreOffice from https://www.libreoffice.org/download/download/');
                return NextResponse.json({
                    error: 'LibreOffice not installed',
                    details: 'Please install LibreOffice from https://www.libreoffice.org/download/download/ and restart the application.',
                    installationGuide: {
                        windows: 'Download from https://www.libreoffice.org/download/download/ and install with default settings',
                        linux: 'Run: sudo apt install libreoffice',
                        mac: 'Run: brew install --cask libreoffice'
                    }
                }, { status: 500 });
            }
        } else {
            libreofficePath = 'libreoffice';
        }

        const libreofficeCmd = `"${libreofficePath}" --headless --convert-to jpg --outdir "${outputDir}" "${tempFilePath}"`;

        console.log('[UPLOAD] Running command:', libreofficeCmd);
        try {
            await execAsync(libreofficeCmd, { maxBuffer: 10 * 1024 * 1024, timeout: 60000 });
            console.log('[UPLOAD] LibreOffice conversion successful');
        } catch (execError) {
            console.error('[UPLOAD] LibreOffice command failed:', (execError as Error).message);
            return NextResponse.json({
                error: 'LibreOffice conversion failed',
                details: (execError as Error).message,
                suggestion: 'Make sure LibreOffice is installed and the file is a valid PPTX'
            }, { status: 500 });
        }

        // Read the generated images
        const files = await readdir(outputDir);
        const jpgFiles = files.filter(f => f.toLowerCase().endsWith('.jpg') || f.toLowerCase().endsWith('.jpeg'));

        if (jpgFiles.length === 0) {
            console.error('[UPLOAD] No images generated');
            return NextResponse.json({ error: 'No images generated from PPTX. LibreOffice may have failed silently.' }, { status: 500 });
        }

        // Sort files to ensure correct slide order
        jpgFiles.sort((a, b) => {
            const numA = parseInt(a.match(/\d+/)?.[0] || '0');
            const numB = parseInt(b.match(/\d+/)?.[0] || '0');
            return numA - numB;
        });

        // Read images and convert to base64
        const images: Array<{ url: string; name: string; data: Buffer }> = [];
        for (const fileName of jpgFiles) {
            const filePath = join(outputDir, fileName);
            const imageBuffer = await readFile(filePath);
            const base64 = imageBuffer.toString('base64');
            images.push({
                url: `data:image/jpeg;base64,${base64}`,
                name: fileName,
                data: imageBuffer
            });
        }

        console.log('[UPLOAD] Returning', images.length, 'images');
        return NextResponse.json({ images });

    } catch (error) {
        console.error('[UPLOAD] ERROR:', (error as Error).message);
        console.error('[UPLOAD] Error type:', (error as Error).constructor.name);

        return NextResponse.json(
            {
                error: (error as Error).message || 'Conversion failed',
                errorType: (error as Error).constructor.name,
                details: error instanceof Error ? error.toString() : 'Unknown error'
            },
            { status: 500 }
        );
    } finally {
        // Cleanup temp file
        if (tempFilePath) {
            try {
                await unlink(tempFilePath);
                console.log('[UPLOAD] Cleaned up temp file');
            } catch {
                // Ignore cleanup errors
            }
        }
    }
}

export async function GET() {
    return NextResponse.json({ message: 'Upload endpoint ready. Use POST to upload a PPTX file.' });
}
