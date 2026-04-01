
import { NextRequest, NextResponse } from 'next/server';
import { writeFile, unlink, mkdir, readdir, readFile } from 'fs/promises';
import { existsSync } from 'fs';
import { join } from 'path';
import { tmpdir } from 'os';
import { exec } from 'child_process';
import { promisify } from 'util';

const execAsync = promisify(exec);

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

        const arrayBuffer = await file.arrayBuffer();
        const buffer = Buffer.from(arrayBuffer);

        const tempDir = tmpdir();
        const fileName = file.name || `upload-${generateId()}.pptx`;
        tempFilePath = join(tempDir, `ppt-${generateId()}-${fileName}`);
        outputDir = join(tempDir, `slides-${generateId()}`);

        console.log('[UPLOAD] Writing temp file');
        await writeFile(tempFilePath, buffer);

        await mkdir(outputDir, { recursive: true });
        console.log('[UPLOAD] Output dir:', outputDir);

        // Find LibreOffice path
        let libreofficePath = '';
        if (process.platform === 'win32') {
            const possiblePaths = [
                'C:\\Program Files\\LibreOffice\\program\\soffice.exe',
                'C:\\Program Files (x86)\\LibreOffice\\program\\soffice.exe',
            ];
            for (const path of possiblePaths) {
                if (existsSync(path)) {
                    libreofficePath = path;
                    break;
                }
            }
            if (!libreofficePath) {
                return NextResponse.json({
                    error: 'LibreOffice not installed',
                    details: 'Download from https://www.libreoffice.org/download/download/'
                }, { status: 500 });
            }
        } else {
            libreofficePath = 'libreoffice';
        }

        // Step 1: Convert PPTX to PDF
        console.log('[UPLOAD] Converting PPTX to PDF...');
        const pdfPath = join(outputDir, 'presentation.pdf');
        try {
            await execAsync(
                `"${libreofficePath}" --headless --convert-to pdf --outdir "${outputDir}" "${tempFilePath}"`,
                { maxBuffer: 50 * 1024 * 1024, timeout: 120000 }
            );
            console.log('[UPLOAD] PDF conversion complete');
        } catch (execError) {
            console.error('[UPLOAD] PDF conversion failed:', (execError as Error).message);
            return NextResponse.json({
                error: 'Conversion failed',
                details: (execError as Error).message
            }, { status: 500 });
        }

        // Step 2: Convert PDF to individual JPG images using pdftoppm or ghostscript
        console.log('[UPLOAD] Converting PDF to individual images...');
        
        // Try pdftoppm first (poppler-utils), then ghostscript, then ImageMagick
        let imageConversionSuccess = false;
        
        // Check for poppler-utils (pdftoppm)
        try {
            await execAsync('where pdftoppm', { timeout: 5000 });
            console.log('[UPLOAD] Using pdftoppm for image conversion');
            
            const pdfFiles = await readdir(outputDir);
            const pdfFile = pdfFiles.find(f => f.toLowerCase().endsWith('.pdf'));
            
            if (pdfFile) {
                const pdfFilePath = join(outputDir, pdfFile);
                // pdftoppm creates files like: outputname-01.jpg, outputname-02.jpg, etc.
                await execAsync(
                    `pdftoppm -jpeg -r 200 "${pdfFilePath}" "${join(outputDir, 'slide')}"`,
                    { maxBuffer: 50 * 1024 * 1024, timeout: 120000 }
                );
                imageConversionSuccess = true;
            }
        } catch {
            console.log('[UPLOAD] pdftoppm not found, trying alternatives...');
        }

        // If pdftoppm failed, try ImageMagick
        if (!imageConversionSuccess) {
            try {
                await execAsync('where magick', { timeout: 5000 });
                console.log('[UPLOAD] Using ImageMagick for image conversion');
                
                const pdfFiles = await readdir(outputDir);
                const pdfFile = pdfFiles.find(f => f.toLowerCase().endsWith('.pdf'));
                
                if (pdfFile) {
                    const pdfFilePath = join(outputDir, pdfFile);
                    await execAsync(
                        `magick -density 200 "${pdfFilePath}" -quality 90 "${join(outputDir, 'slide')}.jpg"`,
                        { maxBuffer: 50 * 1024 * 1024, timeout: 120000 }
                    );
                    imageConversionSuccess = true;
                }
            } catch {
                console.log('[UPLOAD] ImageMagick not found, trying alternatives...');
            }
        }

        // If both failed, try ghostscript
        if (!imageConversionSuccess) {
            try {
                await execAsync('where gswin64c', { timeout: 5000 });
                console.log('[UPLOAD] Using Ghostscript for image conversion');
                
                const pdfFiles = await readdir(outputDir);
                const pdfFile = pdfFiles.find(f => f.toLowerCase().endsWith('.pdf'));
                
                if (pdfFile) {
                    const pdfFilePath = join(outputDir, pdfFile);
                    const outputPattern = join(outputDir, 'slide-%03d.jpg');
                    await execAsync(
                        `gswin64c -dNOPAUSE -dBATCH -sDEVICE=jpeg -r200 -dJPEGQ=90 -sOutputFile="${outputPattern}" "${pdfFilePath}"`,
                        { maxBuffer: 50 * 1024 * 1024, timeout: 120000 }
                    );
                    imageConversionSuccess = true;
                }
            } catch {
                console.log('[UPLOAD] Ghostscript not found');
            }
        }

        // Final fallback: Use LibreOffice to convert PDF to JPG
        if (!imageConversionSuccess) {
            console.log('[UPLOAD] Using LibreOffice to convert PDF to JPG');
            try {
                // Find the PDF file that was created
                const pdfFiles = await readdir(outputDir);
                const pdfFile = pdfFiles.find(f => f.toLowerCase().endsWith('.pdf'));
                
                if (pdfFile) {
                    const pdfFilePath = join(outputDir, pdfFile);
                    // Use LibreOffice to convert PDF to multiple JPG pages
                    await execAsync(
                        `"${libreofficePath}" --headless --convert-to jpg --outdir "${outputDir}" "${pdfFilePath}"`,
                        { maxBuffer: 50 * 1024 * 1024, timeout: 120000 }
                    );
                    imageConversionSuccess = true;
                } else {
                    console.error('[UPLOAD] No PDF file found for conversion');
                }
            } catch {
                console.error('[UPLOAD] LibreOffice PDF to JPG conversion failed');
            }
        }

        // Read the generated images
        const files = await readdir(outputDir);
        console.log('[UPLOAD] Files in output dir:', files);
        
        const imageFiles = files.filter(f => 
            f.toLowerCase().endsWith('.jpg') || 
            f.toLowerCase().endsWith('.jpeg') ||
            f.toLowerCase().endsWith('.png')
        );

        // Sort files to ensure correct slide order
        imageFiles.sort((a, b) => {
            // Extract numbers from filenames like slide-1.jpg, slide-002.jpg
            const numA = parseInt(a.match(/\d+/)?.[0] || '0');
            const numB = parseInt(b.match(/\d+/)?.[0] || '0');
            return numA - numB;
        });

        console.log('[UPLOAD] Found', imageFiles.length, 'images');

        if (imageFiles.length === 0) {
            return NextResponse.json({ error: 'No images generated from PPTX' }, { status: 500 });
        }

        // Read images and convert to base64
        const images: Array<{ url: string; name: string; data: Buffer }> = [];
        for (const imgFile of imageFiles) {
            const filePath = join(outputDir, imgFile);
            const imageBuffer = await readFile(filePath);
            const base64 = imageBuffer.toString('base64');
            images.push({
                url: `data:image/jpeg;base64,${base64}`,
                name: imgFile,
                data: imageBuffer
            });
        }

        console.log('[UPLOAD] Returning', images.length, 'slides');
        return NextResponse.json({ images });

    } catch (error) {
        console.error('[UPLOAD] ERROR:', (error as Error).message);
        return NextResponse.json(
            { error: (error as Error).message || 'Conversion failed' },
            { status: 500 }
        );
    } finally {
        if (tempFilePath) {
            try { await unlink(tempFilePath); } catch { }
        }
    }
}

export async function GET() {
    return NextResponse.json({ message: 'Upload endpoint ready. Use POST to upload a PPTX file.' });
}
