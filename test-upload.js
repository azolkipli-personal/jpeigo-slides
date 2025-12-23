const axios = require('axios');
const FormData = require('form-data');
const fs = require('fs');
const path = require('path');

async function testUpload() {
    const url = 'http://localhost:3000/api/upload';
    const form = new FormData();
    // Create a dummy file
    const filePath = path.join(__dirname, 'test.pptx');
    fs.writeFileSync(filePath, 'dummy content');

    form.append('file', fs.createReadStream(filePath));

    try {
        console.log('Sending request to', url);
        const response = await axios.post(url, form, {
            headers: form.getHeaders(),
            validateStatus: () => true // Don't throw on error status
        });

        console.log('Status:', response.status);
        console.log('Data:', JSON.stringify(response.data, null, 2));
    } catch (e) {
        console.error('Request failed:', e.message);
        if (e.response) {
            console.error('Response data:', e.response.data);
        }
    } finally {
        fs.unlinkSync(filePath);
    }
}

testUpload();
