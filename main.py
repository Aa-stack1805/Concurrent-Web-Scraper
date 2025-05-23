import asyncio
import aiohttp
from bs4 import BeautifulSoup
import csv
import json
from datetime import datetime
import logging
from typing import List, Dict, Optional
from dataclasses import dataclass, asdict
import time
from urllib.parse import urljoin, urlparse

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

@dataclass
class Book:
    #Data class for storing book information
    title: str
    author: str
    price: Optional[float]
    availability: str
    url: str
    source: str
    scraped_at: str
    isbn: Optional[str] = None
    rating: Optional[float] = None

class BookScraper:
    #Concurrent web scraper for collecting book data from multiple sources
    
    def __init__(self, max_concurrent_requests: int = 5, delay_between_requests: float = 0.5):
        self.max_concurrent_requests = max_concurrent_requests
        self.delay_between_requests = delay_between_requests
        self.semaphore = asyncio.Semaphore(max_concurrent_requests)
        self.session = None
        self.results = []
        
    async def __aenter__(self):
        #Async context manager entry
        timeout = aiohttp.ClientTimeout(total=30)
        self.session = aiohttp.ClientSession(timeout=timeout)
        return self
        
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        #Async context manager exit
        if self.session:
            await self.session.close()
    
    async def fetch_page(self, url: str) -> Optional[str]:
        #Fetch a single page with rate limiting
        async with self.semaphore:
            try:
                logger.info(f"Fetching: {url}")
                async with self.session.get(url) as response:
                    if response.status == 200:
                        content = await response.text()
                        await asyncio.sleep(self.delay_between_requests)  # Rate limiting
                        return content
                    else:
                        logger.error(f"Failed to fetch {url}: Status {response.status}")
                        return None
            except Exception as e:
                logger.error(f"Error fetching {url}: {str(e)}")
                return None
    
    async def scrape_books_toscrape(self, page_num: int = 1) -> List[Book]:
        #Scrape books from books.toscrape.com
        books = []
        url = f"https://books.toscrape.com/catalogue/page-{page_num}.html"
        
        html = await self.fetch_page(url)
        if not html:
            return books
            
        soup = BeautifulSoup(html, 'html.parser')
        
        for article in soup.find_all('article', class_='product_pod'):
            try:
                title_elem = article.find('h3').find('a')
                title = title_elem.get('title', '')
                book_url = urljoin(url, title_elem.get('href', ''))
                
                price_elem = article.find('p', class_='price_color')
                price_text = price_elem.text if price_elem else '0'
                price = float(price_text.replace('£', '').replace('Â', ''))
                
                rating_elem = article.find('p', class_='star-rating')
                rating_map = {'One': 1, 'Two': 2, 'Three': 3, 'Four': 4, 'Five': 5}
                rating = rating_map.get(rating_elem.get('class')[1], 0) if rating_elem else None
                
                avail_elem = article.find('p', class_='instock availability')
                availability = 'In stock' if avail_elem else 'Out of stock'
                
                book = Book(
                    title=title,
                    author="Unknown",  # This site doesn't show authors on listing page
                    price=price,
                    availability=availability,
                    url=book_url,
                    source="books.toscrape.com",
                    scraped_at=datetime.now().isoformat(),
                    rating=rating
                )
                books.append(book)
                
            except Exception as e:
                logger.error(f"Error parsing book: {str(e)}")
                continue
        
        return books
    
    async def scrape_openlibrary_search(self, query: str = "python programming") -> List[Book]:
        #Scrape book data from Open Library API
        books = []
        url = f"https://openlibrary.org/search.json?q={query.replace(' ', '+')}&limit=20"
        
        html = await self.fetch_page(url)
        if not html:
            return books
            
        try:
            data = json.loads(html)
            for doc in data.get('docs', [])[:20]:  # Limit to 20 books
                title = doc.get('title', 'Unknown')
                authors = doc.get('author_name', ['Unknown'])
                author = authors[0] if authors else 'Unknown'
                isbn_list = doc.get('isbn', [])
                isbn = isbn_list[0] if isbn_list else None
                
                # Open Library doesn't provide prices
                book = Book(
                    title=title,
                    author=author,
                    price=None,
                    availability="Check Open Library",
                    url=f"https://openlibrary.org/works/{doc.get('key', '')}",
                    source="openlibrary.org",
                    scraped_at=datetime.now().isoformat(),
                    isbn=isbn,
                    rating=doc.get('ratings_average')
                )
                books.append(book)
                
        except Exception as e:
            logger.error(f"Error parsing Open Library data: {str(e)}")
        
        return books
    
    async def scrape_gutenberg_top(self) -> List[Book]:
        #Scrape top books from Project Gutenberg
        books = []
        url = "https://www.gutenberg.org/browse/scores/top"
        
        html = await self.fetch_page(url)
        if not html:
            return books
            
        soup = BeautifulSoup(html, 'html.parser')
        
        # Find the list of top books
        ol_elem = soup.find('ol')
        if ol_elem:
            for li in ol_elem.find_all('li')[:20]:  # Top 20 books
                try:
                    link = li.find('a')
                    if link:
                        title_text = link.text.strip()
                        # Parse title and author
                        if ' by ' in title_text:
                            title, author = title_text.split(' by ', 1)
                        else:
                            title = title_text
                            author = "Unknown"
                        
                        book_url = urljoin(url, link.get('href', ''))
                        
                        book = Book(
                            title=title.strip(),
                            author=author.strip(),
                            price=0.0,  # Gutenberg books are free
                            availability="Free Download",
                            url=book_url,
                            source="gutenberg.org",
                            scraped_at=datetime.now().isoformat()
                        )
                        books.append(book)
                        
                except Exception as e:
                    logger.error(f"Error parsing Gutenberg book: {str(e)}")
                    continue
        
        return books
    
    async def run_all_scrapers(self) -> List[Book]:
        #Run all scrapers concurrently
        tasks = [
            self.scrape_books_toscrape(1),
            self.scrape_books_toscrape(2),
            self.scrape_books_toscrape(3),
            self.scrape_openlibrary_search("python programming"),
            self.scrape_openlibrary_search("data science"),
            self.scrape_gutenberg_top()
        ]
        
        # Run all tasks concurrently
        start_time = time.time()
        results = await asyncio.gather(*tasks, return_exceptions=True)
        end_time = time.time()
        
        logger.info(f"All scraping completed in {end_time - start_time:.2f} seconds")
        
        # Flatten results and handle exceptions
        all_books = []
        for result in results:
            if isinstance(result, Exception):
                logger.error(f"Task failed with error: {str(result)}")
            elif isinstance(result, list):
                all_books.extend(result)
        
        self.results = all_books
        return all_books
    
    def save_to_csv(self, filename: str = "books_data.csv"):
        if not self.results:
            logger.warning("No data to save")
            return
            
        with open(filename, 'w', newline='', encoding='utf-8') as csvfile:
            fieldnames = ['title', 'author', 'price', 'availability', 'url', 
                         'source', 'isbn', 'rating', 'scraped_at']
            writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
            
            writer.writeheader()
            for book in self.results:
                writer.writerow(asdict(book))
        
        logger.info(f"Data saved to {filename}")
    
    def save_to_json(self, filename: str = "books_data.json"):
        if not self.results:
            logger.warning("No data to save")
            return
            
        with open(filename, 'w', encoding='utf-8') as jsonfile:
            json.dump([asdict(book) for book in self.results], 
                     jsonfile, indent=2, ensure_ascii=False)
        
        logger.info(f"Data saved to {filename}")
    
    def get_price_comparison(self) -> Dict[str, List[Book]]:
        comparison = {}
        for book in self.results:
            if book.price is not None:  # Only include books with prices
                if book.title not in comparison:
                    comparison[book.title] = []
                comparison[book.title].append(book)
        
        # Sort each list by price
        for title in comparison:
            comparison[title].sort(key=lambda x: x.price or float('inf'))
        
        return comparison

async def main():
    async with BookScraper(max_concurrent_requests=5, delay_between_requests=0.5) as scraper:
        # Run all scrapers
        books = await scraper.run_all_scrapers()
        
        logger.info(f"Total books scraped: {len(books)}")
        
        # Save to files
        scraper.save_to_csv()
        scraper.save_to_json()
        
        sources = {}
        for book in books:
            sources[book.source] = sources.get(book.source, 0) + 1
        
        print("\n=== Scraping Summary ===")
        print(f"Total books collected: {len(books)}")
        print("\nBooks per source:")
        for source, count in sources.items():
            print(f"  {source}: {count}")
        
        print("\n=== Sample Price Comparisons ===")
        comparisons = scraper.get_price_comparison()
        for title, book_list in list(comparisons.items())[:5]:
            if len(book_list) > 1:
                print(f"\n'{title}':")
                for book in book_list:
                    print(f"  ${book.price:.2f} at {book.source}")

if __name__ == "__main__":
    # Run the async main function
    asyncio.run(main())