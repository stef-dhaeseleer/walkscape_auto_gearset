#!/usr/bin/env python3
"""
Scrape materials from Walkscape wiki and generate materials.json.
Uses Pydantic models for strict schema validation.
"""

import json
import re
import sys
from pathlib import Path
from bs4 import BeautifulSoup
from urllib.parse import unquote

# Add parent directory for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from models import Material, SpecialShopSell
from scraper_utils import *

# Configuration
RESCRAPE = False
MATERIALS_URL = 'https://wiki.walkscape.app/wiki/Materials'
CACHE_DIR = get_cache_dir('materials')
CACHE_FILE = get_cache_file('materials_cache.html')
OUTPUT_FILE = get_output_file('materials.json')
SCAN_FOLDER_FOR_NEW_ITEMS = True

validator = ScraperValidator()

def normalize_id(text: str) -> str:
    """Normalize text to snake_case ID."""
    if not text: return "none"
    text = unquote(text)
    text = text.replace('Special:MyLanguage/', '')
    return text.lower().replace("'", "").replace("-", "_").replace(" ", "_").strip()

def extract_value_and_special_sell(url, name):
    """
    Download individual material page to get its Coin Value and Special Sell info.
    Returns tuple (normal_value, fine_value, special_sell_normal, special_sell_fine)
    """
    slug = url.split('/')[-1]
    cache_file = CACHE_DIR / (sanitize_filename(slug) + '.html')
    html = download_page(url, cache_file, rescrape=RESCRAPE)
    
    value = 0
    fine_value = 0
    special_sell_normal = None
    special_sell_fine = None
    
    if html:
        soup = BeautifulSoup(html, 'html.parser')
        
        # 1. Parse Value from Infobox
        infobox = soup.find('table', class_='ItemInfobox')
        if infobox:
            for row in infobox.find_all('tr'):
                header = row.find('th')
                if not header: continue
                text = header.get_text()
                
                if 'Value' in text and 'Fine Value' not in text:
                    val_cell = row.find('td')
                    if val_cell:
                        v_match = re.search(r'(\d+)', val_cell.get_text())
                        if v_match: value = int(v_match.group(1))
                        
                elif 'Fine Value' in text:
                    val_cell = row.find('td')
                    if val_cell:
                        v_match = re.search(r'(\d+)', val_cell.get_text())
                        if v_match: fine_value = int(v_match.group(1))

        # 2. Parse Special Sale
        special_heading = soup.find('h2', id='Special_Sale')
        if special_heading:
            # The table usually follows the heading
            table = special_heading.find_next('table', class_='wikitable')
            if table:
                rows = table.find_all('tr')[1:] # Skip header
                for row in rows:
                    cells = row.find_all('td')
                    if len(cells) < 2: continue
                    
                    # Logic: identify if row is Normal or Fine based on image alt or row context
                    # The structure is usually: [Icon] [Shop] [Location] [Region] [Item Type (Image)] [Price/Value]
                    # Sometimes rowspan complicates this.
                    
                    item_type_cell = cells[-2]
                    value_cell = cells[-1]
                    
                    is_fine = False
                    img = item_type_cell.find('img')
                    if img and 'Fine' in img.get('alt', ''):
                        is_fine = True
                        
                    # Extract Price (Quantity + Item)
                    price_text = value_cell.get_text(strip=True)
                    qty_match = re.search(r'(\d+)', price_text)
                    if qty_match:
                        qty = int(qty_match.group(1))
                        
                        currency_name = "Unknown"
                        link = value_cell.find('a')
                        if link:
                            currency_name = clean_text(link.get('title', link.get_text()))
                        else:
                            # Fallback to image alt
                            curr_img = value_cell.find('img')
                            if curr_img: currency_name = clean_text(curr_img.get('alt', ''))
                        
                        special_obj = SpecialShopSell(
                            item_id=normalize_id(currency_name),
                            amount=qty
                        )
                        
                        if is_fine:
                            special_sell_fine = special_obj
                        else:
                            special_sell_normal = special_obj

    return value, fine_value, special_sell_normal, special_sell_fine

def parse_materials_list():
    """Parse the main materials table."""
    print("Downloading Materials page...")
    html = download_page(MATERIALS_URL, CACHE_FILE, rescrape=RESCRAPE)
    if not html: return []
    
    soup = BeautifulSoup(html, 'html.parser')
    materials = []
    
    tables = soup.find_all('table', class_='wikitable')
    print(f"Found {len(tables)} tables.")
    
    for table in tables:
        rows = table.find_all('tr')[1:] # Skip header
        for row in rows:
            cells = row.find_all('td')
            if len(cells) < 2: continue
            
            # 1. Name & Link
            link = cells[1].find('a')
            if not link: continue
            
            name = clean_text(link.get_text())
            url = 'https://wiki.walkscape.app' + link.get('href', '')
            slug = link.get('href', '').split('/')[-1]
            
            # 2. Keywords
            keywords = []
            if len(cells) > 2:
                kw_cell = cells[2]
                for kw_link in kw_cell.find_all('a'):
                    if 'Keyword' in kw_link.get('title', ''):
                        keywords.append(clean_text(kw_link.get_text()))
                
                # Fallback: parse text if no links
                if not keywords:
                    raw_text = kw_cell.get_text()
                    if raw_text.strip().lower() != 'none':
                        keywords = [clean_text(k) for k in raw_text.split(',') if k.strip()]

            # 3. Get Details from Page
            val, fine_val, special_norm, special_fine = extract_value_and_special_sell(url, name)
            
            # Create Normal Material
            materials.append(Material(
                id=normalize_id(name),
                wiki_slug=slug,
                name=name,
                value=val,
                keywords=keywords,
                special_sell=special_norm
            ))
            
            # Create Fine Material
            materials.append(Material(
                id=normalize_id(name + "_fine"),
                wiki_slug=slug,
                name=f"{name} (Fine)",
                value=fine_val if fine_val else val,
                keywords=keywords,
                special_sell=special_fine
            ))
            
            print(f"  Processed: {name}")

    return materials

def main():
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    
    materials = parse_materials_list()
    
    # Folder scanning (if strictly needed) could be added here similar to other scrapers
    # by using scan_cache_folder_for_items and parse_individual_page logic
    
    print(f"\nExporting {len(materials)} materials to {OUTPUT_FILE}...")
    data = [m.model_dump(mode='json') for m in materials]
    
    with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

    validator.report()
    print("Done.")

if __name__ == "__main__":
    main()