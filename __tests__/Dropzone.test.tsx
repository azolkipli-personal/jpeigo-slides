
import React from 'react';
import { render, screen } from '@testing-library/react';
import Dropzone from '@/components/Dropzone';
import '@testing-library/jest-dom';

describe('Dropzone', () => {
    it('renders default text', () => {
        render(<Dropzone onFileAccepted={() => { }} isLoading={false} />);
        expect(screen.getByText(/Drag & drop your PowerPoint file here/i)).toBeInTheDocument();
    });

    it('shows loading state', () => {
        render(<Dropzone onFileAccepted={() => { }} isLoading={true} />);
        expect(screen.getByText(/Converting your presentation/i)).toBeInTheDocument();
    });
});
