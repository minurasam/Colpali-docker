import torch
from colpali_engine.models import ColPali, ColPaliProcessor
from PIL import Image
import numpy as np
from pdf2image import convert_from_path
from pathlib import Path
import json
import sys
import os

def extract_and_embed_pdf(pdf_path, output_dir="./embeddings"):
    print("=" * 60)
    print("ColPali PDF Embedding Extractor (Docker)")
    print("=" * 60)
    
    # Check device
    device = "cuda" if torch.cuda.is_available() else "cpu"
    print(f"\n✓ Using device: {device}")
    if device == "cuda":
        print(f"  GPU: {torch.cuda.get_device_name(0)}")
        print(f"  CUDA Version: {torch.version.cuda}")
    
    # Load model
    print("\n⏳ Loading ColPali model...")
    model_name = "vidore/colpali-v1.3"
    
    model = ColPali.from_pretrained(
        model_name,
        torch_dtype=torch.bfloat16 if device == "cuda" else torch.float32,
        device_map=device
    )
    processor = ColPaliProcessor.from_pretrained(model_name)
    print("✓ Model loaded successfully!")
    
    # Convert PDF to images
    print("\n" + "=" * 60)
    print(f"Processing PDF: {pdf_path}")
    print("=" * 60)
    
    print("\n⏳ Converting PDF pages to images...")
    try:
        # In Docker, poppler is already installed and in PATH
        pages = convert_from_path(pdf_path, dpi=200)
        print(f"✓ Extracted {len(pages)} pages")
    except Exception as e:
        print(f"✗ Error converting PDF: {e}")
        return None
    
    # Process each page
    all_embeddings = []
    
    for page_num, page_image in enumerate(pages, 1):
        print(f"\n" + "-" * 60)
        print(f"PAGE {page_num} of {len(pages)}")
        print("-" * 60)
        
        print(f"  Image size: {page_image.size}")
        print(f"  ⏳ Generating embeddings...")
        
        # Process and embed
        batch_images = processor.process_images([page_image]).to(device)
        
        with torch.no_grad():
            embeddings = model(**batch_images)
        
        embeddings_np = embeddings.cpu().numpy()[0]
        
        # Display embedding info
        print(f"\n  EMBEDDING RESULTS:")
        print(f"    Shape: {embeddings_np.shape}")
        print(f"    Number of tokens/patches: {embeddings_np.shape[0]}")
        print(f"    Embedding dimension: {embeddings_np.shape[1]}")
        print(f"    Data type: {embeddings_np.dtype}")
        print(f"    Min value: {embeddings_np.min():.6f}")
        print(f"    Max value: {embeddings_np.max():.6f}")
        print(f"    Mean value: {embeddings_np.mean():.6f}")
        print(f"    Std deviation: {embeddings_np.std():.6f}")
        
        # Show first few token embeddings
        print(f"\n  FIRST 3 TOKEN EMBEDDINGS (first 10 dimensions):")
        for i in range(min(3, len(embeddings_np))):
            print(f"    Token {i}: {embeddings_np[i][:10]}")
        
        # Average pooled embedding
        avg_embedding = embeddings_np.mean(axis=0)
        print(f"\n  AVERAGE POOLED EMBEDDING (first 20 dimensions):")
        print(f"    {avg_embedding[:20]}")
        
        # Store page embeddings
        all_embeddings.append({
            'page': page_num,
            'shape': embeddings_np.shape,
            'embeddings': embeddings_np,
            'avg_embedding': avg_embedding,
            'stats': {
                'min': float(embeddings_np.min()),
                'max': float(embeddings_np.max()),
                'mean': float(embeddings_np.mean()),
                'std': float(embeddings_np.std())
            }
        })
    
    # Save embeddings
    print("\n" + "=" * 60)
    print("SAVING EMBEDDINGS")
    print("=" * 60)
    
    output_path = Path(output_dir)
    output_path.mkdir(exist_ok=True)
    
    pdf_name = Path(pdf_path).stem
    
    # Save as .npy files
    for page_data in all_embeddings:
        page_num = page_data['page']
        output_file = output_path / f"{pdf_name}_page_{page_num}.npy"
        np.save(output_file, page_data['embeddings'])
        print(f"  ✓ Saved: {output_file}")
    
    # Save metadata as JSON
    metadata = {
        'pdf_name': pdf_name,
        'total_pages': len(all_embeddings),
        'embedding_shape': list(all_embeddings[0]['shape']),
        'device': device,
        'pages': [
            {
                'page': p['page'],
                'stats': p['stats']
            }
            for p in all_embeddings
        ]
    }
    
    metadata_file = output_path / f"{pdf_name}_metadata.json"
    with open(metadata_file, 'w') as f:
        json.dump(metadata, f, indent=2)
    print(f"  ✓ Saved metadata: {metadata_file}")
    
    # Summary
    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)
    print(f"Total pages processed: {len(all_embeddings)}")
    print(f"Embeddings per page: {all_embeddings[0]['shape']}")
    print(f"Total embeddings: {len(all_embeddings)} × {all_embeddings[0]['shape'][0]} tokens")
    print(f"Output directory: {output_path.absolute()}")
    
    print("\n" + "=" * 60)
    print("✓ Processing completed!")
    print("=" * 60)
    
    return all_embeddings

def main():
    # Check for PDF files in /app/pdfs
    pdf_dir = Path("/app/pdfs")
    
    if not pdf_dir.exists():
        print(f"Error: PDF directory not found: {pdf_dir}")
        return
    
    pdf_files = list(pdf_dir.glob("*.pdf"))
    
    if not pdf_files:
        print("No PDF files found in /app/pdfs")
        print("Please mount your PDFs to /app/pdfs")
        return
    
    print(f"\nFound {len(pdf_files)} PDF file(s):")
    for i, pdf in enumerate(pdf_files, 1):
        print(f"  {i}. {pdf.name}")
    
    # Process all PDFs or specific one
    if len(sys.argv) > 1:
        # Specific PDF provided as argument
        pdf_name = sys.argv[1]
        pdf_path = pdf_dir / pdf_name
        if pdf_path.exists():
            extract_and_embed_pdf(str(pdf_path), "/app/embeddings")
        else:
            print(f"Error: PDF not found: {pdf_name}")
    else:
        # Process all PDFs
        for pdf_path in pdf_files:
            print("\n" + "#" * 60)
            extract_and_embed_pdf(str(pdf_path), "/app/embeddings")
            print("#" * 60 + "\n")

if __name__ == "__main__":
    main()