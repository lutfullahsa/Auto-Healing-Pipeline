import re
from typing import Any

class PIIMasker:
    """
    Kişisel verileri (PII) maskelemek için kullanılan yardımcı sınıf.
    """
    
    def __init__(self):
        # Regex desenleri
        self.email_regex = re.compile(r'[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+')
        self.iban_regex = re.compile(r'\b[A-Z]{2}\d{2}\s?(?:\d\s?){18,24}\b')
        self.card_regex = re.compile(r'\b(?:\d{4}[-\s]?){3}\d{4}\b')
        self.tckn_regex = re.compile(r'\b[1-9]\d{10}\b')
        self.phone_regex = re.compile(r'\b(?:\+?90|0)?\s?[1-9]\d{2}\s?\d{3}\s?\d{2}\s?\d{2}\b')
        
        # Hassas anahtar kelimeler
        self.sensitive_keys = {'password', 'secret', 'token', 'tc', 'kimlik', 'ssn', 'adres', 'address'}

    def mask_text(self, text: str) -> str:
        if not isinstance(text, str):
            return text
        
        # Spesifikten genele sıralama
        text = self.email_regex.sub('[MASKED_EMAIL]', text)
        text = self.iban_regex.sub('[MASKED_IBAN]', text)
        text = self.card_regex.sub('[MASKED_CARD]', text)
        text = self.tckn_regex.sub('[MASKED_TCKN]', text)
        text = self.phone_regex.sub('[MASKED_PHONE]', text)
        return text

    def mask_records(self, records: list[dict[str, Any]]) -> list[dict[str, Any]]:
        masked_records = []
        for record in records:
            new_record = {}
            for key, value in record.items():
                if any(sk in key.lower() for sk in self.sensitive_keys):
                    new_record[key] = '[MASKED_SENSITIVE]'
                elif isinstance(value, (str, int)):
                    val_str = str(value)
                    masked_val = self.mask_text(val_str)
                    if masked_val != val_str:
                        new_record[key] = masked_val
                    else:
                        new_record[key] = value
                else:
                    new_record[key] = value
            masked_records.append(new_record)
        return masked_records
