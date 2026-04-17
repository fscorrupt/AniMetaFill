import requests
import re
import difflib
from typing import List, Dict, Optional, Any
from app.logger import logger

class SonarrTranslator:
    """
    Interfaces with Sonarr's API to translate show titles into IDs and
    create mappings between absolute episode numbers and SxxExx formats.
    """
    def __init__(self, url: str, api_key: str):
        self.url = url.rstrip('/')
        self.api_key = api_key
        self.headers = {"X-Api-Key": self.api_key}

    def _clean_title(self, title: str) -> str:
        """
        Removes noise from titles to improve matching accuracy. 
        Standardizes punctuation and strips seasonal suffixes that often 
        cause mismatches between Plex and Sonarr metadata.
        """
        # Lowercase and handle common dash differences
        cleaned = title.lower().replace('–', '-').replace('—', '-')
        # Remove years in parentheses
        cleaned = re.sub(r'\s\(\d{4}\)$', '', cleaned)
        # Remove anything after 'season X' to avoid mismatches
        cleaned = re.sub(r'\s-?\s?season\s\d+.*$', '', cleaned)
        # Normalize: keep only alphanumeric and standard spaces/dashes
        cleaned = re.sub(r'[^a-z0-9\s-]', ' ', cleaned)
        # Collapse multiple spaces
        cleaned = re.sub(r'\s+', ' ', cleaned)
        return cleaned.strip()

    def get_series_info(self, title: str) -> Optional[Dict[str, Any]]:
        """
        Retrieves series metadata (ID, TVDB ID, Status, Alt Titles) from Sonarr.
        
        Uses a two-layer matching strategy:
        1. Cleaned exact match against the main title, sort title, and all alt titles.
        2. Fuzzy match (difflib) as a fallback for subtle naming differences.
        """
        try:
            cleaned_target = self._clean_title(title)
            
            response = requests.get(
                f"{self.url}/api/v3/series",
                headers=self.headers,
                timeout=10
            )
            response.raise_for_status()
            series_list = response.json()
            
            candidate_list = []
            
            for series in series_list:
                s_titles = [
                    series.get('title', ''),
                    series.get('sortTitle', '')
                ]
                # Also check alternate titles
                if 'alternateTitles' in series:
                    for alt in series['alternateTitles']:
                        s_titles.append(alt.get('title', ''))
                
                for s_title in s_titles:
                    c_s_title = self._clean_title(s_title)
                    # 1. Exact match after cleaning both
                    if cleaned_target == c_s_title:
                        return {
                            "id": series['id'],
                            "tvdb_id": series.get('tvdbId'),
                            "status": series['status'],
                            "genres": series.get('genres', []),
                            "alternate_titles": [series.get('title', '')] + [alt.get('title', '') for alt in series.get('alternateTitles', [])]
                        }
                    
                    # Store candidate for fuzzy fallback
                    if c_s_title and c_s_title not in candidate_list:
                        candidate_list.append(c_s_title)

            # 2. Fuzzy fallback if no exact clean match
            best_matches = difflib.get_close_matches(cleaned_target, candidate_list, n=1, cutoff=0.85)
            if best_matches:
                best_c_title = best_matches[0]
                # Find the series ID for this candidate
                for series in series_list:
                    check_titles = [series.get('title', ''), series.get('sortTitle', '')]
                    if 'alternateTitles' in series:
                        check_titles.extend([alt.get('title', '') for alt in series['alternateTitles']])
                    
                    if any(self._clean_title(t) == best_c_title for t in check_titles):
                        logger.search("Sonarr", f"Fuzzy match: '{title}' -> '{series.get('title')}'")
                        return {
                            "id": series['id'],
                            "tvdb_id": series.get('tvdbId'),
                            "status": series['status'],
                            "genres": series.get('genres', []),
                            "alternate_titles": [series.get('title', '')] + [alt.get('title', '') for alt in series.get('alternateTitles', [])]
                        }
                    
            return None
        except Exception as e:
            logger.error(f"Sonarr search error: {e}")
            return None

    def get_absolute_to_season_map(self, series_id: int) -> Dict[int, str]:
        """
        Maps absolute episode numbers to SxxExx strings.
        Includes a mathematical fallback if absolute numbers are missing in Sonarr.
        """
        try:
            response = requests.get(
                f"{self.url}/api/v3/episode",
                params={"seriesId": series_id},
                headers=self.headers,
                timeout=10
            )
            response.raise_for_status()
            episodes = response.json()
            
            # Sort episodes by seasonNumber then episodeNumber
            # Ignore specials (season 0) for absolute mapping consistency
            standard_episodes = [
                ep for ep in episodes 
                if ep.get('seasonNumber', 0) > 0
            ]
            standard_episodes.sort(key=lambda x: (x['seasonNumber'], x['episodeNumber']))
            
            abs_map = {}
            calculated_abs = 1
            
            for ep in standard_episodes:
                season = ep['seasonNumber']
                episode_num = ep['episodeNumber']
                s_e_format = f"S{season:02d}E{episode_num:02d}"
                
                # Check if Sonarr already has an absolute number
                actual_abs = ep.get('absoluteEpisodeNumber', 0)
                
                # Use actual absolute number if available, otherwise fallback to calculated
                mapping_abs = actual_abs if actual_abs and actual_abs > 0 else calculated_abs
                
                abs_map[mapping_abs] = s_e_format
                
                # Increment calculated absolute counter
                calculated_abs += 1
                
            logger.info(f"Sonarr mapping created: {len(abs_map)} episodes.")
            return abs_map
        except Exception as e:
            logger.error(f"Error creating absolute map: {e}")
            return {}
