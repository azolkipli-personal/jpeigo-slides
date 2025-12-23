
import React from 'react';
import { render, screen } from '@testing-library/react';
import Gallery from '@/components/Gallery';
import '@testing-library/jest-dom';

describe('Gallery', () => {
    it('renders nothing when empty', () => {
        const { container } = render(<Gallery images={[]} />);
        expect(container).toBeEmptyDOMElement();
    });

    it('renders images', () => {
        const images = [{ url: 'http://example.com/slide1.jpg' }, { url: 'http://example.com/slide2.jpg' }];
        render(<Gallery images={images} />);
        expect(screen.getByText('Generated Slides (2)')).toBeInTheDocument();
        expect(screen.getAllByRole('img')).toHaveLength(2);
    });
});
