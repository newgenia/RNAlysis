# -*- coding: utf-8 -*-

"""Top-level package for sRNA analysis pipeline."""
import os

__name__ = "rnalysis"
__author__ = """Guy Teichman"""
__email__ = 'guyteichman@gmail.com'
__version__ = '1.3.2'
__gene_names_and_biotype__ = os.path.join(os.path.dirname(__file__), 'gene_names_and_biotype.csv')
__settings_start_phrase__ = 'reference_table_path='
__biotype_file_start_phrase__ = 'biotype_reference_path'

