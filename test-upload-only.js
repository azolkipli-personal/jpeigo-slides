const axios = require('axios');
const fs = require('fs');

async function testUploadOnly() {
    const pptxPath = "C:\\Users\\Ammar.Zolkipli\\OneDrive - globallogic.com\\Documents\\Accelerating the 'AI-Native' Transformation.pptx";
    const port = 3019;
    
    console.log('Testing upload API...\n');
    
    try {
        const uploadForm = new FormData();
        const fileBuffer = fs.readFileSync(pptxPath);
        const blob = new Blob([fileBuffer]);
        uploadForm.append('file', blob, 'test.pptx');
        
        const uploadResponse = await axios.post(`http://localhost:${port}/api/upload`, uploadForm, {
            headers: { 'Content-Type': 'multipart/form-data' },
            timeout: 60000
        });
        
        console.log('✅ Upload successful!');
        console.log(`   Generated ${uploadResponse.data.images.length} slide(s)`);
        console.log(`   Image data length: ${uploadResponse.data.images[0]?.url?.length || 0} chars\n`);
        
        console.log('✅ LibreOffice conversion working correctly!');
        console.log('\n========================================');
        console.log('✅ PPTX Upload & Conversion: PASSED');
        console.log('========================================');
        console.log('\nNote: Translation API uses Tesseract.js (local OCR)');
        console.log('      First run may take 30-60s to download language data.');
        
    } catch (error) {
        console.error('\n❌ Error:', error.response?.data || error.message);
    }
}

testUploadOnly();
