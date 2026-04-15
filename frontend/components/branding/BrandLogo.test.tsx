import React from 'react';
import { render, screen } from '@testing-library/react';
import { BrandLogo } from './BrandLogo';

jest.mock('next/image', () => ({
  __esModule: true,
  default: (props: React.ImgHTMLAttributes<HTMLImageElement>) => {
    // eslint-disable-next-line @next/next/no-img-element
    return <img alt={props.alt ?? ''} {...props} />;
  },
}));

describe('BrandLogo', () => {
  it('renders the compact lockup by default', () => {
    render(<BrandLogo />);

    expect(screen.getByAltText('QPrisma logo')).toBeInTheDocument();
    expect(screen.getByText('QPrisma')).toBeInTheDocument();
  });

  it('renders only the icon mark when requested', () => {
    render(<BrandLogo variant="mark" />);

    expect(screen.getByAltText('QPrisma logo')).toBeInTheDocument();
    expect(screen.queryByText('QPrisma')).not.toBeInTheDocument();
  });

  it('renders the full brand heading and tagline', () => {
    render(<BrandLogo as="h1" variant="full" />);

    expect(screen.getByRole('heading', { name: /qprisma: ai video/i })).toBeInTheDocument();
    expect(screen.getByText('Intelligence Accelerator')).toBeInTheDocument();
  });
});
