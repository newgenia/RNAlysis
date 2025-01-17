"""
This module can perform enrichment analyses on a given set of genomic features and visualize their intersections. \
These include gene ontology/tissue/phenotype enrichment, enrichment for user-defined attributes, \
set visualization ,etc. \
Results of enrichment analyses can be saved to .csv files.
"""
import functools
import itertools
import types
import warnings
from pathlib import Path
from typing import Dict, Iterable, List, Set, Tuple, Union

from rnalysis.utils.param_typing import GO_ASPECTS, GO_EVIDENCE_TYPES, GO_QUALIFIERS, DEFAULT_ORGANISMS, GENE_ID_TYPES

try:
    from typing import Literal
except ImportError:
    from typing_extensions import Literal

import matplotlib.pyplot as plt
import matplotlib
import matplotlib_venn as vn
import numpy as np
import pandas as pd
import upsetplot

from rnalysis.filtering import Filter
from rnalysis.utils import io, parsing, settings, validation, enrichment_runner, generic


class FeatureSet:
    """ Receives a filtered gene set and the set's name (optional) and preforms various enrichment analyses on them. """
    __slots__ = {'gene_set': 'set of feature names/indices', 'set_name': 'name of the FeatureSet'}

    def __init__(self, gene_set: Union[List[str], Set[str], 'Filter'] = None, set_name: str = ''):

        """
        :param gene_set: the set of genomic features to be used in downstream analyses
        :type gene_set: filtering.Filter object, set of strings or list of strings
        :param set_name: name of the FeatureSet
        :type set_name: str


        :Examples:
            >>> from rnalysis import enrichment, filtering
            >>> my_set = enrichment.FeatureSet({'gene1','gene2','gene2'}, 'name of my set')

            >>> filter_obj = filtering.CountFilter('tests/test_files/counted.csv')
            >>> my_other_set = enrichment.FeatureSet(filter_obj, 'name of my other set')

        """
        assert isinstance(set_name, str), f"'set_name' must be of type str, instead got {type(set_name)}."
        if gene_set is None:
            gene_set = parsing.data_to_set(parsing.from_string(
                "Please insert genomic features/indices separated by newline \n"
                "(example: \n'WBGene00000001\nWBGene00000002\nWBGene00000003')", delimiter='\n'))
        elif validation.isinstanceinh(gene_set, Filter):
            gene_set = gene_set.index_set
        else:
            gene_set = parsing.data_to_set(gene_set)
        self.gene_set = gene_set
        self.set_name = set_name

    def __copy__(self):
        obj = type(self).__new__(type(self))
        obj.gene_set = self.gene_set.copy()
        obj.set_name = self.set_name
        return obj

    def __repr__(self):
        return f"{self.__class__.__name__}: '{self.set_name}'"

    def __len__(self):
        return len(self.gene_set)

    def __contains__(self, item):
        return True if item in self.gene_set else False

    def __iter__(self):
        return self.gene_set.__iter__()

    def __eq__(self, other):
        if type(self) != type(other):
            return False

        if self.set_name != other.set_name:
            return False

        if self.gene_set != other.gene_set:
            return False

        return True

    def change_set_name(self, new_name: str):
        """
        Change the 'set_name' of a FeatureSet to a new name.

        :param new_name: the new set name
        :type new_name: str

        """
        assert isinstance(new_name, str), f"New set name must be of type str. Instead, got {type(new_name)}"
        self.set_name = new_name

    def save_txt(self, fname: Union[str, Path]):

        """
        Save the list of features in the FeatureSet object under the specified filename and path.

        :type fname: str or pathlib.Path
        :param fname: full filename/path for the output file. Can include the '.txt' suffix but doesn't have to.

        """
        assert isinstance(fname, (str, Path)), "fname must be str or pathlib.Path!"
        if isinstance(fname, str):
            if not fname.endswith('.txt'):
                fname = fname + '.txt'
        elif isinstance(fname, Path):
            if not fname.suffix == '.txt':
                fname = Path(f"{str(fname.parent)}{fname.name}.txt")
        with open(fname, 'w') as f:
            for i, gene in enumerate(self.gene_set):
                line = gene + '\n' if (i + 1) < len(self.gene_set) else gene
                f.write(line)

    def _set_ops(self, others: Union[set, 'FeatureSet', Tuple[Union[set, 'FeatureSet']]],
                 op: types.FunctionType) -> set:

        """
        Performs a given set operation on self and on another object (FeatureSet or set).
        :type others: FeatureSet or set
        :param others: Other object to perform set operation with.
        :type: op: Callable (set.union, set.intersection, set.difference or set.symmetric difference)
        :param op: The set operation to be performed.
        :return: A set resulting from the set operation.

        """
        others = list(others)
        for i, other in enumerate(others):
            if isinstance(other, set):
                pass
            elif isinstance(other, FeatureSet):
                others[i] = other.gene_set
            else:
                raise TypeError("'other' must be an FeatureSet object or a set!")
        try:
            return op(self.gene_set, *others)
        except TypeError as e:
            if op == set.symmetric_difference:
                raise TypeError(
                    f"Symmetric difference can only be calculated for two objects, {len(others) + 1} were given!")
            else:
                raise e

    def union(self, *others: Union[set, 'FeatureSet']) -> 'FeatureSet':

        """
         Calculates the set union of the indices from multiple FeatureSet objects \
        (the indices that exist in at least one of the FeatureSet objects).

        :type others: FeatureSet or set
        :param others: The objects against which the current object will be compared.
        :return: a new FeatureSet with elements from this FeatureSet and all other objects.
        :rtype: FeatureSet

        :Examples:
            >>> from rnalysis import enrichment
            >>> en = enrichment.FeatureSet({'WBGene00000004','WBGene00000005','WBGene00000006'}, 'set name')
            >>> en2 = enrichment.FeatureSet({'WBGene00000004','WBGene00000001'})
            >>> s = {'WBGene00000001','WBGene00000002','WBGene00000003'}
            >>> en.union(s, en2)
            >>> print(en)
            FeatureSet: set name
            {'WBGene00000003', 'WBGene00000004', 'WBGene00000001', 'WBGene00000002', 'WBGene00000006', 'WBGene00000005'}

        """
        return FeatureSet(self._set_ops(others, set.union))

    def intersection(self, *others: Union[set, 'FeatureSet']) -> 'FeatureSet':

        """
        Calculates the set intersection of the indices from multiple FeatureSet objects \
        (the indices that exist in ALL of the FeatureSet objects).

        :type others: FeatureSet, RankedSet or set
        :param others: The objects against which the current object will be compared.
        :return: a new FeatureSet with elements common to this FeatureSet and all other objects.
        :rtype: FeatureSet

        :Examples:
            >>> from rnalysis import enrichment
            >>> en = enrichment.FeatureSet({'WBGene00000001','WBGene00000002','WBGene00000006'}, 'set name')
            >>> s = {'WBGene00000001','WBGene00000002','WBGene00000003'}
            >>> en2 = enrichment.FeatureSet({'WBGene00000004','WBGene00000001'})
            >>> en.intersection(s, en2)
            >>> print(en)
            FeatureSet: set name
            {'WBGene00000001'}

        """
        return FeatureSet(self._set_ops(others, set.intersection))

    def difference(self, *others: Union[set, 'FeatureSet']) -> 'FeatureSet':

        """
        Calculates the set difference of the indices from multiple FeatureSet objects \
        (the indices that appear in the first FeatureSet object but NOT in the other objects).

        :type others: FeatureSet, RankedSet or set
        :param others: The objects against which the current object will be compared.
        :return: a new FeatureSet with elements in this FeatureSet that are not in the other objects.
        :rtype: FeatureSet

        :Examples:
            >>> from rnalysis import enrichment
            >>> en = enrichment.FeatureSet({'WBGene00000001','WBGene00000002','WBGene00000006'}, 'set name')
            >>> s = {'WBGene00000001','WBGene00000002','WBGene00000003'}
            >>> en2 = enrichment.FeatureSet({'WBGene00000004','WBGene00000001'})
            >>> en.difference(s, en2)
            >>> print(en)
            FeatureSet: set name
            {'WBGene00000006'}

        """
        return FeatureSet(self._set_ops(others, set.difference))

    def symmetric_difference(self, other: Union[set, 'FeatureSet']) -> 'FeatureSet':

        """
        Calculates the set symmetric difference of the indices from two FeatureSet objects \
        (the indices that appear in EXACTLY ONE of the FeatureSet objects, and not both/neither). \
        A-symmetric difference-B is equivalent to (A-difference-B)-union-(B-difference-A).

        :type other: FeatureSet, RankedSet or set
        :param other: A second object against which the current object will be compared.
        :return: a new FeatureSet with elements in either this FeatureSet or the other object, but not both.
        :rtype: FeatureSet

        :Examples:
            >>> from rnalysis import enrichment
            >>> en = enrichment.FeatureSet({'WBGene00000001','WBGene00000002','WBGene00000006'}, 'set name')
            >>> en2 = enrichment.FeatureSet({'WBGene00000004','WBGene00000001'})
            >>> en.symmetric_difference(en2)
            >>> print(en)
            FeatureSet: set name
            {'WBGene00000002', 'WBGene00000006', 'WBGene00000004'}

        """
        return FeatureSet(self._set_ops((other,), set.symmetric_difference))

    def go_enrichment(self, organism: Union[str, int, Literal['auto'], Literal[DEFAULT_ORGANISMS]] = 'auto',
                      gene_id_type: Union[str, Literal['auto'], Literal[GENE_ID_TYPES]] = 'auto', alpha: float = 0.05,
                      statistical_test: Literal['fisher', 'hypergeometric', 'randomization'] = 'fisher',
                      biotype: Union[str, List[str], Literal['all']] = 'all',
                      background_genes: Union[Set[str], Filter, 'FeatureSet'] = None,
                      biotype_ref_path: Union[str, Path, Literal['predefined']] = 'predefined',
                      propagate_annotations: Literal['classic', 'elim', 'weight', 'all.m', 'no'] = 'elim',
                      aspects: Union[Literal[('any',) + GO_ASPECTS], Iterable[Literal[GO_ASPECTS]]] = 'any',
                      evidence_types: Union[
                          Literal[('any',) + GO_EVIDENCE_TYPES], Iterable[Literal[GO_EVIDENCE_TYPES]]] = 'any',
                      excluded_evidence_types: Union[Literal[GO_EVIDENCE_TYPES], Iterable[Literal[
                          GO_EVIDENCE_TYPES]]] = (),
                      databases: Union[str, Iterable[str]] = 'any',
                      excluded_databases: Union[str, Iterable[str]] = (),
                      qualifiers: Union[Literal[('any',) + GO_QUALIFIERS], Iterable[Literal[GO_QUALIFIERS]]] = 'any',
                      excluded_qualifiers: Union[Literal[GO_QUALIFIERS], Iterable[Literal[GO_QUALIFIERS]]] = 'not',
                      return_nonsignificant: bool = False,
                      save_csv: bool = False, fname=None, return_fig: bool = False, plot_horizontal: bool = True,
                      plot_ontology_graph: bool = True, ontology_graph_format: Literal['pdf', 'svg', 'png'] = 'pdf',
                      randomization_reps: int = 10000, random_seed: Union[int, None] = None,
                      parallel: bool = True, gui_mode: bool = False
                      ) -> Union[pd.DataFrame, Tuple[pd.DataFrame, plt.Figure]]:
        """
        Calculates enrichment and depletion of the FeatureSet for Gene Ontology (GO) terms against a background set. \
        The GO terms and annotations are drawn via the GO Solr search engine GOlr, \
        using the search terms defined by the user. \
        The background set is determined by either the input variable ‘background_genes’, \
        or by the input variable ‘biotype’ and a Biotype Reference Table. \
        P-values are corrected for multiple comparisons using the Benjamini–Hochberg step-up procedure \
        (original FDR method). In plots, for the clarity of display, complete depletion (linear enrichment score = 0) \
        appears with the smallest value in the scale.

        :param organism: organism name or NCBI taxon ID for which the function will fetch GO annotations.
        :type organism: str or int
        :param gene_id_type: the identifier type of the genes/features in the FeatureSet object \
        (for example: 'UniProtKB', 'WormBase', 'RNACentral', 'Entrez Gene ID'). \
        If the annotations fetched from the GOLR server do not match your gene_id_type, RNAlysis will attempt to map \
        the annotations' gene IDs to your identifier type. \
        For a full list of legal 'gene_id_type' names, see the UniProt website: \
        https://www.uniprot.org/help/api_idmapping
        :type gene_id_type: str or 'auto' (default='auto')
        :type alpha: float between 0 and 1 (default=0.05)
        :param alpha: Indicates the FDR threshold for significance.
        :param statistical_test: determines the statistical test to be used for enrichment analysis. \
        Note that some propagation methods support only some of the available statistical tests.
        :type statistical_test: 'fisher', 'hypergeometric' or 'randomization' (default='fisher')
        :type biotype: str specifying a specific biotype, list/set of strings each specifying a biotype, or 'all'. \
        Default 'protein_coding'.
        :param biotype: determines the background genes by their biotype. Requires specifying a Biotype Reference Table. \
        'all' will include all genomic features in the reference table, \
        'protein_coding' will include only protein-coding genes from the reference table, etc. \
        Cannot be specified together with 'background_genes'.
        :type background_genes: set of feature indices, filtering.Filter object, or enrichment.FeatureSet object
        :param background_genes: a set of specific feature indices to be used as background genes. \
        Cannot be specified together with 'biotype'.
        :type biotype_ref_path: str or pathlib.Path (default='predefined')
        :param biotype_ref_path: the path of the Biotype Reference Table. \
        Will be used to generate background set if 'biotype' is specified.
        :param propagate_annotations: determines the propagation method of GO annotations. \
        'no' does not propagate annotations at all; 'classic' propagates all annotations up to the DAG tree's root; \
        'elim' terminates propagation at nodes which show significant enrichment; 'weight' performs propagation in a \
        weighted manner based on the significance of children nodes relatively to their parents; and 'allm' uses a \
        combination of all proopagation methods. To read more about the propagation methods, \
        see Alexa et al: https://pubmed.ncbi.nlm.nih.gov/16606683/
        :type propagate_annotations: 'classic', 'elim', 'weight', 'all.m', or 'no' (default='elim')
        :param aspects: only annotations from the specified GO aspects will be included in the analysis. \
        Legal aspects are 'biological_process' (P), 'molecular_function' (F), and 'cellular_component' (C).
        :type aspects: str, Iterable of str, 'biological_process', 'molecular_function', 'cellular_component', \
        or 'any' (default='any')
        :param evidence_types: only annotations with the specified evidence types will be included in the analysis. \
        For a full list of legal evidence codes and evidence code categories see the GO Consortium website: \
        http://geneontology.org/docs/guide-go-evidence-codes/
        :type evidence_types: str, Iterable of str, 'experimental', 'phylogenetic' ,'computational', 'author', \
        'curator', 'electronic', or 'any' (default='any')
        :param excluded_evidence_types: annotations with the specified evidence types will be \
        excluded from the analysis. \
        For a full list of legal evidence codes and evidence code categories see the GO Consortium website: \
        http://geneontology.org/docs/guide-go-evidence-codes/
        :type excluded_evidence_types: str, Iterable of str, 'experimental', 'phylogenetic' ,'computational', \
        'author', 'curator', 'electronic', or None (default=None)
        :param databases: only annotations from the specified databases will be included in the analysis. \
        For a full list of legal databases see the GO Consortium website:
        http://amigo.geneontology.org/xrefs
        :type databases: str, Iterable of str, or 'any' (default)
        :param excluded_databases: annotations from the specified databases will be excluded from the analysis. \
        For a full list of legal databases see the GO Consortium website:
        http://amigo.geneontology.org/xrefs
        :type excluded_databases: str, Iterable of str, or None (default)
        :param qualifiers: only annotations with the speficied qualifiers will be included in the analysis. \
        Legal qualifiers are 'not', 'contributes_to', and/or 'colocalizes_with'.
        :type qualifiers: str, Iterable of str, or 'any' (default)
        :param excluded_qualifiers: annotations with the speficied qualifiers will be excluded from the analysis. \
        Legal qualifiers are 'not', 'contributes_to', and/or 'colocalizes_with'.
        :type excluded_qualifiers: str, Iterable of str, or None (default='not')
        :param return_nonsignificant: if True, the results DataFrame will include all tested GO terms - \
        both significant and non-significant terms. If False (default), only significant GO terms will be returned.
        :type return_nonsignificant: bool (default=False)
        :type save_csv: bool, default False
        :param save_csv: If True, will save the results to a .csv file, under the name specified in 'fname'.
        :type fname: str or pathlib.Path
        :param fname: The full path and name of the file to which to save the results. For example: \
        'C:/dir/file'. No '.csv' suffix is required. If None (default), fname will be requested in a manual prompt.
        :type return_fig: bool (default=False)
        :param return_fig: if True, returns a matplotlib Figure object in addition to the results DataFrame.
        :type plot_ontology_graph: bool (default=True)
        :param plot_ontology_graph: if True, will generate an ontology graph depicting the \
        significant GO terms and their parent nodes.
        :type ontology_graph_format: str (default='pdf')
        :param ontology_graph_format: the file format the ontology graph will be generated in.
        :type plot_horizontal: bool (default=True)
        :param plot_horizontal: if True, results will be plotted with a horizontal bar plot. \
        Otherwise, results will be plotted with a vertical plot.
        :type random_seed: non-negative integer (default=None)
        :type random_seed: if using a randomization test, determine the random seed used to initialize \
        the pseudorandom generator for the randomization test. \
        By default it is picked at random, but you can set it to a particular integer to get consistents results \
        over multiple runs. If not using a randomization test, this parameter will not affect the analysis.
        :param randomization_reps: if using a randomization test, determine how many randomization repititions to run. \
        Otherwise, this parameter will not affect the analysis.
        :type randomization_reps: int larger than 0 (default=10000)
        :type parallel: bool (default=False)
        :param parallel: if True, will calculate the statistical tests using parallel processing. \
        In most cases parallel processing will lead to shorter computation time, but does not affect the results of \
        the analysis otherwise.
        :rtype: pd.DataFrame (default) or Tuple[pd.DataFrame, matplotlib.figure.Figure]
        :return: a pandas DataFrame with GO terms as rows/index; \
        and a matplotlib Figure, if 'return_figure' is set to True.

        .. figure:: /figures/ontology_graph.png
           :align:   center
           :scale: 60 %

           Example plot of go_enrichment(plot_ontology_graph=True)


        .. figure:: /figures/plot_enrichment_results_go.png
           :align:   center
           :scale: 60 %

           Example plot of go_enrichment()


        .. figure:: /figures/plot_enrichment_results_go_vertical.png
           :align:   center
           :scale: 60 %

           Example plot of go_enrichment(plot_horizontal = False)
        """
        propagate_annotations = propagate_annotations.lower()
        if validation.isinstanceinh(background_genes, FeatureSet):
            background_genes = background_genes.gene_set
        if statistical_test.lower() == 'randomization':
            kwargs = dict(reps=randomization_reps, random_seed=random_seed)
        else:
            kwargs = {}
        runner = enrichment_runner.GOEnrichmentRunner(self.gene_set, organism, gene_id_type, alpha,
                                                      propagate_annotations, aspects, evidence_types,
                                                      excluded_evidence_types, databases, excluded_databases,
                                                      qualifiers, excluded_qualifiers, return_nonsignificant, save_csv,
                                                      fname, return_fig, plot_horizontal, plot_ontology_graph,
                                                      self.set_name, parallel, statistical_test, biotype,
                                                      background_genes, biotype_ref_path,
                                                      ontology_graph_format=ontology_graph_format, **kwargs)

        if gui_mode:
            return runner.run(plot=False), runner
        return runner.run()

    def kegg_enrichment(self, organism: Union[str, int, Literal['auto'], Literal[DEFAULT_ORGANISMS]] = 'auto',
                        gene_id_type: Union[str, Literal['auto'], Literal[GENE_ID_TYPES]] = 'auto',
                        alpha: float = 0.05,
                        statistical_test: Literal['fisher', 'hypergeometric', 'randomization'] = 'fisher',
                        biotype: Union[str, List[str], Literal['all']] = 'all',
                        background_genes: Union[Set[str], Filter, 'FeatureSet'] = None,
                        biotype_ref_path: Union[str, Path, Literal['predefined']] = 'predefined',
                        return_nonsignificant: bool = False,
                        save_csv: bool = False, fname=None, return_fig: bool = False, plot_horizontal: bool = True,
                        randomization_reps: int = 10000, random_seed: Union[int, None] = None,
                        parallel: bool = True, gui_mode: bool = False
                        ) -> Union[pd.DataFrame, Tuple[pd.DataFrame, plt.Figure]]:
        """
        Calculates enrichment and depletion of the FeatureSet for Kyoto Encyclopedia of Genes and Genomes (KEGG) \
        curated pathways against a background set. \
        The background set is determined by either the input variable ‘background_genes’, \
        or by the input variable ‘biotype’ and a Biotype Reference Table. \
        P-values are corrected for multiple comparisons using the Benjamini–Hochberg step-up procedure \
        (original FDR method). In plots, for the clarity of display, complete depletion (linear enrichment score = 0) \
        appears with the smallest value in the scale.

        :param organism: organism name or NCBI taxon ID for which the function will fetch GO annotations.
        :type organism: str or int
        :param gene_id_type: the identifier type of the genes/features in the FeatureSet object \
        (for example: 'UniProtKB', 'WormBase', 'RNACentral', 'Entrez Gene ID'). \
        If the annotations fetched from the KEGG server do not match your gene_id_type, RNAlysis will attempt to map \
        the annotations' gene IDs to your identifier type. \
        For a full list of legal 'gene_id_type' names, see the UniProt website: \
        https://www.uniprot.org/help/api_idmapping
        :type gene_id_type: str or 'auto' (default='auto')
        :type alpha: float between 0 and 1 (default=0.05)
        :param alpha: Indicates the FDR threshold for significance.
        :param statistical_test: determines the statistical test to be used for enrichment analysis. \
        Note that some propagation methods support only some of the available statistical tests.
        :type statistical_test: 'fisher', 'hypergeometric' or 'randomization' (default='fisher')
        :type biotype: str specifying a specific biotype, list/set of strings each specifying a biotype, or 'all'. \
        Default 'protein_coding'.
        :param biotype: determines the background genes by their biotype. Requires specifying a Biotype Reference Table. \
        'all' will include all genomic features in the reference table, \
        'protein_coding' will include only protein-coding genes from the reference table, etc. \
        Cannot be specified together with 'background_genes'.
        :type background_genes: set of feature indices, filtering.Filter object, or enrichment.FeatureSet object
        :param background_genes: a set of specific feature indices to be used as background genes. \
        Cannot be specified together with 'biotype'.
        :type biotype_ref_path: str or pathlib.Path (default='predefined')
        :param biotype_ref_path: the path of the Biotype Reference Table. \
        Will be used to generate background set if 'biotype' is specified.
        :param return_nonsignificant: if True, the results DataFrame will include all tested pathways - \
        both significant and non-significant ones. If False (default), only significant pathways will be returned.
        :type return_nonsignificant: bool (default=False)
        :type save_csv: bool, default False
        :param save_csv: If True, will save the results to a .csv file, under the name specified in 'fname'.
        :type fname: str or pathlib.Path
        :param fname: The full path and name of the file to which to save the results. For example: \
        'C:/dir/file'. No '.csv' suffix is required. If None (default), fname will be requested in a manual prompt.
        :type return_fig: bool (default=False)
        :param return_fig: if True, returns a matplotlib Figure object in addition to the results DataFrame.
        :type plot_horizontal: bool (default=True)
        :param plot_horizontal: if True, results will be plotted with a horizontal bar plot. \
        Otherwise, results will be plotted with a vertical plot.
        :type random_seed: non-negative integer (default=None)
        :type random_seed: if using a randomization test, determine the random seed used to initialize \
        the pseudorandom generator for the randomization test. \
        By default it is picked at random, but you can set it to a particular integer to get consistents results \
        over multiple runs. If not using a randomization test, this parameter will not affect the analysis.
        :param randomization_reps: if using a randomization test, determine how many randomization repititions to run. \
        Otherwise, this parameter will not affect the analysis.
        :type randomization_reps: int larger than 0 (default=10000)
        :type parallel: bool (default=False)
        :param parallel: if True, will calculate the statistical tests using parallel processing. \
        In most cases parallel processing will lead to shorter computation time, but does not affect the results of \
        the analysis otherwise.
        :rtype: pd.DataFrame (default) or Tuple[pd.DataFrame, matplotlib.figure.Figure]
        :return: a pandas DataFrame with the indicated pathway names as rows/index; \
        and a matplotlib Figure, if 'return_figure' is set to True.


        .. figure:: /figures/plot_enrichment_results_kegg.png
           :align:   center
           :scale: 60 %

           Example plot of kegg_enrichment()


        .. figure:: /figures/plot_enrichment_results_kegg_vertical.png
           :align:   center
           :scale: 60 %

           Example plot of kegg_enrichment(plot_horizontal = False)
        """
        if validation.isinstanceinh(background_genes, FeatureSet):
            background_genes = background_genes.gene_set
        if statistical_test.lower() == 'randomization':
            kwargs = dict(reps=randomization_reps, random_seed=random_seed)
        else:
            kwargs = {}
        runner = enrichment_runner.KEGGEnrichmentRunner(self.gene_set, organism, gene_id_type, alpha,
                                                        return_nonsignificant, save_csv, fname, return_fig,
                                                        plot_horizontal, self.set_name, parallel, statistical_test,
                                                        biotype, background_genes, biotype_ref_path, **kwargs)

        if gui_mode:
            return runner.run(plot=False), runner
        return runner.run()

    def enrich_randomization(self, attributes: Union[Iterable[str], str, Iterable[int], int] = None,
                             alpha: float = 0.05, reps: int = 10000,
                             biotype: Union[str, List[str], Literal['all']] = 'protein_coding',
                             background_genes: Union[Set[str], Filter, 'FeatureSet'] = None,
                             attr_ref_path: Union[str, Path, Literal['predefined']] = 'predefined',
                             biotype_ref_path: Union[str, Path, Literal['predefined']] = 'predefined',
                             return_nonsignificant: bool = True,
                             save_csv: bool = False, fname=None, return_fig: bool = False, plot_horizontal: bool = True,
                             random_seed: Union[int, None] = None, parallel: bool = False
                             ) -> Union[pd.DataFrame, Tuple[pd.DataFrame, plt.Figure]]:

        """
        This function is depracated; please user 'FeatureSet.user_defined_enrichment' instead. \
        Calculates enrichment and depletion of the FeatureSet for user-defined attributes against a background set \
        using a randomization test. The attributes are drawn from an Attribute Reference Table. \
        The background set is determined by either the input variable ‘background_genes’, \
        or by the input variable ‘biotype’ and a Biotype Reference Table. P-values are calculated using a \
        randomization test with the formula p = (successes + 1)/(repeats + 1). \
        This formula results in a positively-biased estimator of the real p-value \
        (a conservative estimate of p-value). When the number of reps approaches infinity, \
        the formula results in an unbiased estimator of the real p-value. \
        P-values are corrected for multiple comparisons using the Benjamini–Hochberg step-up procedure \
        (original FDR method). In plots, for the clarity of display, complete depletion (linear enrichment = 0) \
        appears with the smallest value in the scale.

        :type attributes: str, int, iterable (list, tuple, set, etc) of str/int, or 'all'
        :param attributes: An iterable of attribute names or attribute numbers \
        (according to their order in the Attribute Reference Table). \
        If 'all', all of the attributes in the Attribute Reference Table will be used. \
        If None, a manual input prompt will be raised.
        :type alpha: float between 0 and 1 (default=0.05)
        :param alpha: Indicates the FDR threshold for significance.
        :type reps: int larger than 0 (default=10000)
        :param reps: How many repetitions to run the randomization for. \
        10,000 is the default. Recommended 10,000 or higher.
        :type biotype: str specifying a specific biotype, list/set of strings each specifying a biotype, or 'all'. \
        (default='protein_coding')
        :param biotype: determines the background genes by their biotype. Requires specifying a Biotype Reference Table. \
        'all' will include all genomic features in the reference table, \
        'protein_coding' will include only protein-coding genes from the reference table, etc. \
        Cannot be specified together with 'background_genes'.
        :type background_genes: set of feature indices, filtering.Filter object, or enrichment.FeatureSet object \
        (default=None)
        :param background_genes: a set of specific feature indices to be used as background genes. \
        :type attr_ref_path: str or pathlib.Path (default='predefined')
        :param attr_ref_path: the path of the Attribute Reference Table from which user-defined attributes will be drawn.
        :type biotype_ref_path: str or pathlib.Path (default='predefined')
        :param biotype_ref_path: the path of the Biotype Reference Table. \
        Will be used to generate background set if 'biotype' is specified.
        Cannot be specified together with 'biotype'.
        :param return_nonsignificant: if True (default), the results DataFrame will include all tested attributes - \
        both significant and non-significant ones. If False, only significant attributes will be returned.
        :type return_nonsignificant: bool (default=True)
        :type save_csv: bool (default=False)
        :param save_csv: If True, will save the results to a .csv file, under the name specified in 'fname'.
        :type fname: str or pathlib.Path (default=None)
        :param fname: The full path and name of the file to which to save the results. For example: \
        'C:/dir/file'. No '.csv' suffix is required. If None (default), fname will be requested in a manual prompt.
        :type return_fig: bool (default=False)
        :param return_fig: if True, returns a matplotlib Figure object in addition to the results DataFrame.
        :type plot_horizontal: bool (default=True)
        :param plot_horizontal: if True, results will be plotted with a horizontal bar plot. Otherwise, results \
        will be plotted with a vertical plot.
        :type random_seed: non-negative integer (default=None)
        :type random_seed: The random seed used to initialize the pseudorandom generator for the randomization test. \
        By default it is picked at random, but you can set it to a particular integer to get consistents results \
        over multiple runs.
        :type parallel: bool (default=False)
        :param parallel: if True, will calculate the statistical tests using parallel processing. \
        In most cases parallel processing will lead to shorter computation time, but does not affect the results of \
        the analysis otherwise.
        :rtype: pd.DataFrame (default) or Tuple[pd.DataFrame, matplotlib.figure.Figure]
        :return: a pandas DataFrame with the indicated attribute names as rows/index; \
        and a matplotlib Figure, if 'return_figure' is set to True.

        .. figure:: /figures/plot_enrichment_results.png
           :align:   center
           :scale: 60 %

           Example plot of enrich_randomization()


        .. figure:: /figures/plot_enrichment_results_vertical.png
           :align:   center
           :scale: 60 %

           Example plot of enrich_randomization(plot_horizontal = False)

        """
        warnings.warn("This function is depracated, and will be removed in the next major release. "
                      "Use the function 'FeatureSet.user_defined_enrichment()' instead.")
        if validation.isinstanceinh(background_genes, FeatureSet):
            background_genes = background_genes.gene_set
        runner = enrichment_runner.EnrichmentRunner(self.gene_set, attributes, alpha, attr_ref_path,
                                                    return_nonsignificant, save_csv, fname, return_fig, plot_horizontal,
                                                    self.set_name, parallel, 'randomization', biotype, background_genes,
                                                    biotype_ref_path, single_set=False, random_seed=random_seed,
                                                    reps=reps)
        return runner.run()

    def user_defined_enrichment(self, attributes: Union[List[str], str, List[int], int, Literal['all']],
                                statistical_test: Literal['fisher', 'hypergeometric', 'randomization'] = 'fisher',
                                alpha: float = 0.05, biotype: Union[str, List[str], Literal['all']] = 'all',
                                background_genes: Union[Set[str], Filter, 'FeatureSet'] = None,
                                attr_ref_path: Union[str, Path, Literal['predefined']] = 'predefined',
                                biotype_ref_path: Union[str, Path, Literal['predefined']] = 'predefined',
                                return_nonsignificant: bool = True,
                                save_csv: bool = False, fname=None, return_fig: bool = False,
                                plot_horizontal: bool = True, randomization_reps: int = 10000,
                                random_seed: Union[int, None] = None, parallel: bool = True, gui_mode: bool = False
                                ) -> Union[pd.DataFrame, Tuple[pd.DataFrame, plt.Figure]]:
        """
        Calculates enrichment and depletion of the FeatureSet for user-defined attributes against a background set.\
        The attributes are drawn from an Attribute Reference Table. \
        The background set is determined by either the input variable ‘background_genes’, \
        or by the input variable ‘biotype’ and a Biotype Reference Table. \
        P-values are corrected for multiple comparisons using the Benjamini–Hochberg step-up procedure \
        (original FDR method). In plots, for the clarity of display, complete depletion (linear enrichment score = 0) \
        appears with the smallest value in the scale.

        :type attributes: str, int, iterable (list, tuple, set, etc) of str/int, or 'all'.
        :param attributes: An iterable of attribute names or attribute numbers \
        (according to their order in the Attribute Reference Table). \
        If 'all', all of the attributes in the Attribute Reference Table will be used. \
        If None, a manual input prompt will be raised.
        :param statistical_test: determines the statistical test to be used for enrichment analysis. \
        Note that some propagation methods support only some of the available statistical tests.
        :type statistical_test: 'fisher', 'hypergeometric' or 'randomization' (default='fisher')
        :type alpha: float between 0 and 1 (default=0.05)
        :param alpha: Indicates the FDR threshold for significance.
        :type attr_ref_path: str or pathlib.Path (default='predefined')
        :param attr_ref_path: the path of the Attribute Reference Table from which user-defined attributes will be drawn.
        :type biotype_ref_path: str or pathlib.Path (default='predefined')
        :param biotype_ref_path: the path of the Biotype Reference Table. \
        Will be used to generate background set if 'biotype' is specified.
        :type biotype: str specifying a specific biotype, list/set of strings each specifying a biotype, or 'all' \
        (default='protein_coding')
        :param biotype: determines the background genes by their biotype. Requires specifying a Biotype Reference Table. \
        'all' will include all genomic features in the reference table, \
        'protein_coding' will include only protein-coding genes from the reference table, etc. \
        Cannot be specified together with 'background_genes'.
        :type background_genes: set of feature indices, filtering.Filter object, or enrichment.FeatureSet object \
        (default=None)
        :param background_genes: a set of specific feature indices to be used as background genes. \
        Cannot be specified together with 'biotype'.
        :param return_nonsignificant: if True (default), the results DataFrame will include all tested attributes - \
        both significant and non-significant ones. If False, only significant attributes will be returned.
        :type return_nonsignificant: bool (default=True)
        :type save_csv: bool (default=False)
        :param save_csv: If True, will save the results to a .csv file, under the name specified in 'fname'.
        :type fname: str or pathlib.Path (default=None)
        :param fname: The full path and name of the file to which to save the results. For example: \
        'C:/dir/file'. No '.csv' suffix is required. If None (default), fname will be requested in a manual prompt.
        :type return_fig: bool (default=False)
        :param return_fig: if True, returns a matplotlib Figure object in addition to the results DataFrame.
        :type plot_horizontal: bool (default=True)
        :param plot_horizontal: if True, results will be plotted with a horizontal bar plot. Otherwise, results \
        will be plotted with a vertical plot.
        :type random_seed: non-negative integer (default=None)
        :type random_seed: if using a randomization test, determine the random seed used to initialize \
        the pseudorandom generator for the randomization test. \
        By default it is picked at random, but you can set it to a particular integer to get consistents results \
        over multiple runs. If not using a randomization test, this parameter will not affect the analysis.
        :param randomization_reps: if using a randomization test, determine how many randomization repititions to run. \
        Otherwise, this parameter will not affect the analysis.
        :type randomization_reps: int larger than 0 (default=10000)
        :type parallel: bool (default=True)
        :param parallel: if True, will calculate the statistical tests using parallel processing. \
        In most cases parallel processing will lead to shorter computation time, but does not affect the results of \
        the analysis otherwise.
        :rtype: pd.DataFrame (default) or Tuple[pd.DataFrame, matplotlib.figure.Figure]
        :return: a pandas DataFrame with the indicated attribute names as rows/index; \
        and a matplotlib Figure, if 'return_figure' is set to True.

        .. figure:: /figures/plot_enrichment_results.png
           :align:   center
           :scale: 60 %

           Example plot of user_defined_enrichment()


        .. figure:: /figures/plot_enrichment_results_vertical.png
           :align:   center
           :scale: 60 %

           Example plot of user_defined_enrichment(plot_horizontal = False)

        """
        if validation.isinstanceinh(background_genes, FeatureSet):
            background_genes = background_genes.gene_set
        if statistical_test == 'randomization':
            kwargs = dict(reps=randomization_reps)
        else:
            kwargs = dict()
        runner = enrichment_runner.EnrichmentRunner(self.gene_set, attributes, alpha, attr_ref_path,
                                                    return_nonsignificant, save_csv, fname, return_fig, plot_horizontal,
                                                    self.set_name, parallel, statistical_test, biotype,
                                                    background_genes, biotype_ref_path, single_set=False,
                                                    random_seed=random_seed, **kwargs)
        if gui_mode:
            return runner.run(plot=False), runner
        return runner.run()

    def enrich_hypergeometric(self, attributes: Union[Iterable[str], str, Iterable[int], int] = None,
                              alpha: float = 0.05, biotype: Union[str, List[str], Literal['all']] = 'protein_coding',
                              background_genes: Union[Set[str], Filter, 'FeatureSet'] = None,
                              attr_ref_path: Union[str, Path, Literal['predefined']] = 'predefined',
                              biotype_ref_path: Union[str, Path, Literal['predefined']] = 'predefined',
                              return_nonsignificant: bool = True,
                              save_csv: bool = False, fname=None, return_fig: bool = False,
                              plot_horizontal: bool = True, parallel: bool = True
                              ) -> Union[pd.DataFrame, Tuple[pd.DataFrame, plt.Figure]]:

        """
        This function is depracated; please user 'FeatureSet.user_defined_enrichment' instead. \
        Calculates enrichment and depletion of the FeatureSet for user-defined attributes against a background set \
        using the Hypergeometric Test. The attributes are drawn from an Attribute Reference Table. \
        The background set is determined by either the input variable ‘background_genes’, \
        or by the input variable ‘biotype’ and a Biotype Reference Table. \
        P-values are calculated using a hypergeometric test: \
        Given M genes in the background set, n genes in the test set, \
        with N genes from the background set belonging to a specific attribute (or 'success') \
        and X genes from the test set belonging to that attribute. \
        If we were to randomly draw n genes from the background set (without replacement), \
        what is the probability of drawing X or more (in case of enrichment)/X or less (in case of depletion) \
        genes belonging to the given attribute? \
        P-values are corrected for multiple comparisons using the Benjamini–Hochberg step-up procedure \
        (original FDR method). In plots, for the clarity of display, complete depletion (linear enrichment score = 0) \
        appears with the smallest value in the scale.

        :type attributes: str, int, iterable (list, tuple, set, etc) of str/int, or 'all'.
        :param attributes: An iterable of attribute names or attribute numbers \
        (according to their order in the Attribute Reference Table). \
        If 'all', all of the attributes in the Attribute Reference Table will be used. \
        If None, a manual input prompt will be raised.
        :type alpha: float between 0 and 1 (default=0.05)
        :param alpha: Indicates the FDR threshold for significance.
        :type attr_ref_path: str or pathlib.Path (default='predefined')
        :param attr_ref_path: the path of the Attribute Reference Table from which user-defined attributes will be drawn.
        :type biotype_ref_path: str or pathlib.Path (default='predefined')
        :param biotype_ref_path: the path of the Biotype Reference Table. \
        Will be used to generate background set if 'biotype' is specified.
        :type biotype: str specifying a specific biotype, list/set of strings each specifying a biotype, or 'all' \
        (default='protein_coding')
        :param biotype: determines the background genes by their biotype. Requires specifying a Biotype Reference Table. \
        'all' will include all genomic features in the reference table, \
        'protein_coding' will include only protein-coding genes from the reference table, etc. \
        Cannot be specified together with 'background_genes'.
        :type background_genes: set of feature indices, filtering.Filter object, or enrichment.FeatureSet object \
        (default=None)
        :param background_genes: a set of specific feature indices to be used as background genes. \
        Cannot be specified together with 'biotype'.
        :param return_nonsignificant: if True (default), the results DataFrame will include all tested attributes - \
        both significant and non-significant ones. If False, only significant attributes will be returned.
        :type return_nonsignificant: bool (default=True)
        :type save_csv: bool (default=False)
        :param save_csv: If True, will save the results to a .csv file, under the name specified in 'fname'.
        :type fname: str or pathlib.Path (default=None)
        :param fname: The full path and name of the file to which to save the results. For example: \
        'C:/dir/file'. No '.csv' suffix is required. If None (default), fname will be requested in a manual prompt.
        :type return_fig: bool (default=False)
        :param return_fig: if True, returns a matplotlib Figure object in addition to the results DataFrame.
        :type plot_horizontal: bool (default=True)
        :param plot_horizontal: if True, results will be plotted with a horizontal bar plot. Otherwise, results \
        will be plotted with a vertical plot.
        :type parallel: bool (default=True)
        :param parallel: if True, will calculate the statistical tests using parallel processing. \
        In most cases parallel processing will lead to shorter computation time, but does not affect the results of \
        the analysis otherwise.
        :rtype: pd.DataFrame (default) or Tuple[pd.DataFrame, matplotlib.figure.Figure]
        :return: a pandas DataFrame with the indicated attribute names as rows/index; \
        and a matplotlib Figure, if 'return_figure' is set to True.

        .. figure:: /figures/plot_enrichment_results.png
           :align:   center
           :scale: 60 %

           Example plot of enrich_hypergeometric()


        .. figure:: /figures/plot_enrichment_results_vertical.png
           :align:   center
           :scale: 60 %

           Example plot of enrich_hypergeometric(plot_horizontal = False)

        """
        warnings.warn("This function is depracated, and will be removed in the next major release. "
                      "Use the function 'FeatureSet.user_defined_enrichment()' instead.")
        if validation.isinstanceinh(background_genes, FeatureSet):
            background_genes = background_genes.gene_set
        runner = enrichment_runner.EnrichmentRunner(self.gene_set, attributes, alpha, attr_ref_path,
                                                    return_nonsignificant, save_csv, fname, return_fig, plot_horizontal,
                                                    self.set_name, parallel, 'hypergeometric', biotype,
                                                    background_genes, biotype_ref_path, single_set=False)
        return runner.run()

    def non_categorical_enrichment(self, attributes: Union[List[str], str, List[int], int, Literal['all']] = None,
                                   alpha: float = 0.05, parametric_test: bool = False,
                                   biotype: Union[str, List[str], Literal['all']] = 'all',
                                   background_genes: Union[Set[str], Filter, 'FeatureSet'] = None,
                                   attr_ref_path: Union[str, Path, Literal['predefined']] = 'predefined',
                                   biotype_ref_path: Union[str, Path, Literal['predefined']] = 'predefined',
                                   plot_log_scale: bool = True,
                                   plot_style: Literal['interleaved', 'overlap'] = 'overlap', n_bins: int = 50,
                                   save_csv: bool = False, fname=None, return_fig: bool = False, gui_mode: bool = False
                                   ) -> Union[pd.DataFrame, Tuple[pd.DataFrame, List[plt.Figure]]]:
        """
        Calculates enrichment and depletion of the FeatureSet for user-defined non-categorical attributes \
        against a background set using either a one-sample T-test or Sign test. \
        The attributes are drawn from an Attribute Reference Table. \
        The background set is determined by either the input variable ‘background_genes’, \
        or by the input variable ‘biotype’ and a Biotype Reference Table. \
        P-values are corrected for multiple comparisons using the Benjamini–Hochberg step-up procedure \
        (original FDR method).

        :type attributes: str, int, iterable (list, tuple, set, etc) of str/int, or 'all'.
        :param attributes: An iterable of attribute names or attribute numbers \
        (according to their order in the Attribute Reference Table). \
        If 'all', all of the attributes in the Attribute Reference Table will be used. \
        If None, a manual input prompt will be raised.
        :type alpha: float between 0 and 1 (default=0.05)
        :param alpha: Indicates the FDR threshold for significance.
        :param parametric_test: if True, performs a parametric statistical test (one-sample t-test). \
        If False (default), performs a non-parametric statistical test (sign test).
        :type parametric_test: bool (default=False)
        :type biotype: str specifying a specific biotype, list/set of strings each specifying a biotype, or 'all' \
        (default='protein_coding')
        :param biotype: determines the background genes by their biotype. Requires specifying a Biotype Reference Table. \
        'all' will include all genomic features in the reference table, \
        'protein_coding' will include only protein-coding genes from the reference table, etc. \
        Cannot be specified together with 'background_genes'.
        :type background_genes: set of feature indices, filtering.Filter object, or enrichment.FeatureSet object \
        (default=None)
        :param background_genes: a set of specific feature indices to be used as background genes. \
        Cannot be specified together with 'biotype'.
        :type attr_ref_path: str or pathlib.Path (default='predefined')
        :param attr_ref_path: the path of the Attribute Reference Table from which user-defined attributes will be drawn.
        :type biotype_ref_path: str or pathlib.Path (default='predefined')
        :param biotype_ref_path: the path of the Biotype Reference Table. \
        Will be used to generate background set if 'biotype' is specified.
        :param plot_log_scale: if True (default), the Y-axis of the enrichment plot will be logarithmic. \
        Otherwise, the Y-axis of the enrichment plot will be linear.
        :type plot_log_scale: bool (default=True)
        :param plot_style: 'interleaved' will plot an interleaved histogram. \
        'overlap' will plot a semi-transparent histogram where the obsreved and expected are overlapping.
        :type plot_style: 'overlap' or 'interleaved' (default='overlap')
        :param n_bins: the number of bins to display in the enrichment plot histograms
        :type n_bins: int larger than 0 (default=50)
        :type save_csv: bool (default=False)
        :param save_csv: If True, will save the results to a .csv file, under the name specified in 'fname'.
        :type fname: str or pathlib.Path (default=None)
        :param fname: The full path and name of the file to which to save the results. For example: \
        'C:/dir/file'. No '.csv' suffix is required. If None (default), fname will be requested in a manual prompt.
        :type return_fig: bool (default=False)
        :param return_fig: if True, returns a matplotlib Figure object in addition to the results DataFrame.
        :rtype: pd.DataFrame (default) or Tuple[pd.DataFrame, matplotlib.figure.Figure]
        :return: a pandas DataFrame with the indicated attribute names as rows/index; \
        and a matplotlib Figure, if 'return_figure' is set to True.


        .. figure:: /figures/hist_overlap.png
           :align:   center
           :scale: 60 %

           Example plot of non_categorical_enrichment(plot_style`='overlap')

        .. figure:: /figures/hist_interleaved.png
           :align:   center
           :scale: 60 %

           Example plot of non_categorical_enrichment(plot_style='interleaved')
        """

        if validation.isinstanceinh(background_genes, FeatureSet):
            background_genes = background_genes.gene_set
        runner = enrichment_runner.NonCategoricalEnrichmentRunner(self.gene_set, attributes, alpha, biotype,
                                                                  background_genes, attr_ref_path,
                                                                  biotype_ref_path, save_csv, fname,
                                                                  return_fig, plot_log_scale, plot_style,
                                                                  n_bins, self.set_name, parallel=False,
                                                                  parametric_test=parametric_test)
        if gui_mode:
            return runner.run(plot=False), runner
        return runner.run()

    def biotypes(self, ref: Union[str, Path, Literal['predefined']] = 'predefined'):

        """
        Returns a DataFrame of the biotypes in the gene set and their count.

        :type ref: str or pathlib.Path (default='predefined')
        :param ref: Path of the reference file used to determine biotype. \
        Default is the path predefined in the settings file.

        :Examples:
            >>> from rnalysis import enrichment, filtering
            >>> d = filtering.Filter("tests/test_files/test_deseq.csv")
            >>> en = enrichment.FeatureSet(d)
            >>> en.biotypes(ref='tests/biotype_ref_table_for_tests.csv')
                            gene
            biotype
            protein_coding    26
            pseudogene         1
            unknown            1

        """

        ref = settings.get_biotype_ref_path(ref)
        ref_df = io.load_csv(ref)
        validation.validate_biotype_table(ref_df)
        ref_df.columns = ref_df.columns.str.lower()
        not_in_ref = pd.Index(self.gene_set).difference(set(ref_df['gene']))
        if len(not_in_ref) > 0:
            warnings.warn(
                f'{len(not_in_ref)} of the features in the Filter object do not appear in the Biotype Reference Table. ')
            ref_df = ref_df.append(pd.DataFrame({'gene': not_in_ref, 'biotype': '_missing_from_biotype_reference'}))
        return ref_df.set_index('gene', drop=False).loc[self.gene_set].groupby('biotype').count()


class RankedSet(FeatureSet):
    """
    Receives a ranked gene set, sorted by any biologically-meaningful value (expression level, fold-change, etc)\
     and preforms various enrichment analyses on them. \
     ALl functions that can be applied to FeatureSet objects can also be applied to RankedSet objects.
    """
    __slots__ = {'ranked_genes': 'a vector of feature names/indices ordered by rank'}

    def __init__(self, ranked_genes: Union[Filter, List[str], Tuple[str], np.ndarray], set_name: str = ''):

        if validation.isinstanceinh(ranked_genes, Filter):
            self.ranked_genes = ranked_genes.df.index.values.astype('str', copy=True)
        elif isinstance(ranked_genes, (list, tuple)):
            self.ranked_genes = np.array(ranked_genes, dtype='str')
        elif isinstance(ranked_genes, np.ndarray):
            self.ranked_genes = ranked_genes.astype('str', copy=True)
        elif isinstance(ranked_genes, set):
            raise TypeError("'ranked_genes' must be an array, list, tuple or Filter object, sorted by rank. "
                            "Python sets are not a valid type ofr 'ranked_genes'.")
        elif isinstance(ranked_genes, dict):
            raise TypeError("Generating a RankedSet from a dictionary is not implemented yet.")
        else:
            raise TypeError(f"'ranked_genes' must be an array, list, tuple or Filter object, sorted by rank. "
                            f"Instead got {type(ranked_genes)}.")

        super().__init__(ranked_genes, set_name)
        assert len(self.ranked_genes) == len(self.gene_set), f"'ranked_genes' must have no repeating elements!"

    def __copy__(self):
        obj = type(self).__new__(type(self))
        obj.ranked_genes = self.ranked_genes.copy()
        obj.gene_set = self.gene_set.copy()
        obj.set_name = self.set_name
        return obj

    def __iter__(self):
        return self.ranked_genes.__iter__()

    def __eq__(self, other):
        if type(self) != type(other):
            return False

        if self.set_name != other.set_name:
            return False

        if len(self.ranked_genes) != len(other.ranked_genes) or not np.all(self.ranked_genes == other.ranked_genes):
            return False

        return True

    def _set_ops(self, others: Union[set, 'FeatureSet'], op: types.FunctionType):
        warnings.warn("Warning: when performing set operations with RankedSet objects, "
                      "the return type will always be FeatureSet and not RankedSet.")
        return super()._set_ops(others, op)

    def single_set_go_enrichment(self, organism: Union[str, int, Literal['auto'], Literal[DEFAULT_ORGANISMS]] = 'auto',
                                 gene_id_type: Union[str, Literal['auto'], Literal[GENE_ID_TYPES]] = 'auto',
                                 alpha: float = 0.05,
                                 propagate_annotations: Literal['classic', 'elim', 'weight', 'all.m', 'no'] = 'elim',
                                 aspects: Union[Literal[('any',) + GO_ASPECTS], Iterable[Literal[GO_ASPECTS]]] = 'any',
                                 evidence_types: Union[
                                     Literal[('any',) + GO_EVIDENCE_TYPES], Iterable[Literal[
                                         GO_EVIDENCE_TYPES]]] = 'any',
                                 excluded_evidence_types: Union[
                                     Literal[GO_EVIDENCE_TYPES], Iterable[Literal[GO_EVIDENCE_TYPES]]] = (),
                                 databases: Union[str, Iterable[str]] = 'any',
                                 excluded_databases: Union[str, Iterable[str]] = (),
                                 qualifiers: Union[
                                     Literal[('any',) + GO_QUALIFIERS], Iterable[Literal[GO_QUALIFIERS]]] = 'any',
                                 excluded_qualifiers: Union[
                                     Literal[GO_QUALIFIERS], Iterable[Literal[GO_QUALIFIERS]]] = 'not',
                                 return_nonsignificant: bool = False,
                                 save_csv: bool = False, fname=None,
                                 return_fig: bool = False, plot_horizontal: bool = True,
                                 plot_ontology_graph: bool = True, ontology_graph_format: str = 'pdf',
                                 parallel: bool = True, gui_mode: bool = False
                                 ) -> Union[pd.DataFrame, Tuple[pd.DataFrame, plt.Figure]]:
        """
        Calculates enrichment and depletion of the sorted RankedSet for Gene Ontology (GO) terms \
        WITHOUT a background set, using the generalized Minimum Hypergeometric Test (XL-mHG, developed by  \
        `Prof. Zohar Yakhini and colleagues <https://dx.doi.org/10.1371/journal.pcbi.0030039/>`_ \
        and generalized by \
        `Florian Wagner <https://journals.plos.org/plosone/article?id=10.1371/journal.pone.0143196/>`_). \
        The GO terms and annotations are drawn via the GO Solr search engine GOlr, \
        using the search terms defined by the user. \
        P-values are calculated using the generalized Minimum Hypergeometric Test. \
        P-values are corrected for multiple comparisons using the Benjamini–Hochberg step-up procedure \
        (original FDR method). In plots, for the clarity of display, complete depletion (linear enrichment = 0) \
        appears with the smallest value in the scale.

        :param organism: organism name or NCBI taxon ID for which the function will fetch GO annotations.
        :type organism: str or int
        :param gene_id_type: the identifier type of the genes/features in the FeatureSet object \
        (for example: 'UniProtKB', 'WormBase', 'RNACentral', 'Entrez Gene ID'). \
        If the annotations fetched from the GOLR server do not match your gene_id_type, \
        RNAlysis will attempt to map  the annotations' gene IDs to your identifier type. \
        For a full list of legal 'gene_id_type' names, see the UniProt website: \
        https://www.uniprot.org/help/api_idmapping
        :type gene_id_type: str or 'auto' (default='auto')
        :type alpha: float between 0 and 1
        :param alpha: Indicates the FDR threshold for significance.
        :param propagate_annotations: determines the propagation method of GO annotations. \
        'no' does not propagate annotations at all; 'classic' propagates all annotations up to the DAG tree's root; \
        'elim' terminates propagation at nodes which show significant enrichment; 'weight' performs propagation in a \
        weighted manner based on the significance of children nodes relatively to their parents; and 'allm' uses a \
        combination of all proopagation methods. To read more about the propagation methods, \
        see Alexa et al: https://pubmed.ncbi.nlm.nih.gov/16606683/
        :type propagate_annotations: 'classic', 'elim', 'weight', 'all.m', or 'no' (default='elim')
        :param aspects: only annotations from the specified GO aspects will be included in the analysis. \
        Legal aspects are 'biological_process' (P), 'molecular_function' (F), and 'cellular_component' (C).
        :type aspects: str, Iterable of str, 'biological_process', 'molecular_function', 'cellular_component', \
        or 'any' (default='any')
        :param evidence_types: only annotations with the specified evidence types \
        will be included in the analysis. \
        For a full list of legal evidence codes and evidence code categories see the GO Consortium website: \
        http://geneontology.org/docs/guide-go-evidence-codes/
        :type evidence_types: str, Iterable of str, 'experimental', 'phylogenetic' ,'computational', 'author', \
        'curator', 'electronic', or 'any' (default='any')
        :param excluded_evidence_types: annotations with the specified evidence types will be \
        excluded from the analysis. \
        For a full list of legal evidence codes and evidence code categories see the GO Consortium website: \
        http://geneontology.org/docs/guide-go-evidence-codes/
        :type excluded_evidence_types: str, Iterable of str, 'experimental', 'phylogenetic' ,'computational', \
        'author', 'curator', 'electronic', or None (default=None)
        :param databases: only annotations from the specified databases will be included in the analysis. \
        For a full list of legal databases see the GO Consortium website:
        http://amigo.geneontology.org/xrefs
        :type databases: str, Iterable of str, or 'any' (default)
        :param excluded_databases: annotations from the specified databases \
        will be excluded from the analysis. \
        For a full list of legal databases see the GO Consortium website:
        http://amigo.geneontology.org/xrefs
        :type excluded_databases: str, Iterable of str, or None (default)
        :param qualifiers: only annotations with the speficied qualifiers will be included in the analysis. \
        Legal qualifiers are 'not', 'contributes_to', and/or 'colocalizes_with'.
        :type qualifiers: str, Iterable of str, or 'any' (default)
        :param excluded_qualifiers: annotations with the speficied qualifiers \
        will be excluded from the analysis. \
        Legal qualifiers are 'not', 'contributes_to', and/or 'colocalizes_with'.
        :type excluded_qualifiers: str, Iterable of str, or None (default='not')
        :param return_nonsignificant: if True, the results DataFrame will include all tested GO terms - \
        both significant and non-significant terms. If False (default), \
        only significant GO terms will be returned.
        :type return_nonsignificant: bool (default=False)
        :type save_csv: bool, default False
        :param save_csv: If True, will save the results to a .csv file, under the name specified in 'fname'.
        :type fname: str or pathlib.Path
        :param fname: The full path and name of the file to which to save the results. For example: \
        'C:/dir/file'. No '.csv' suffix is required. If None (default), \
        fname will be requested in a manual prompt.
        :type return_fig: bool (default=False)
        :param return_fig: if True, returns a matplotlib Figure object in addition to the results DataFrame.
        :type plot_horizontal: bool (default=True)
        :param plot_horizontal: if True, results will be plotted with a horizontal bar plot. \
        Otherwise, results will be plotted with a vertical plot.
        :type plot_ontology_graph: bool (default=True)
        :param plot_ontology_graph: if True, will generate an ontology graph depicting the \
        significant GO terms and their parent nodes.
        :type ontology_graph_format: str (default='pdf')
        :param ontology_graph_format: the file format the ontology graph will be generated in.
        :type parallel: bool (default=True)
        :param parallel: if True, will calculate the statistical tests using parallel processing. \
        In most cases parallel processing will lead to shorter computation time, but does not affect the results of \
        the analysis otherwise.
        :rtype: pd.DataFrame (default) or Tuple[pd.DataFrame, matplotlib.figure.Figure]
        :return: a pandas DataFrame with the indicated attribute names as rows/index; \
        and a matplotlib Figure, if 'return_figure' is set to True.

        .. figure:: /figures/ontology_graph_singlelist.png
           :align:   center
           :scale: 60 %

           Example plot of single_set_go_enrichment(plot_ontology_graph=True)


        .. figure:: /figures/plot_enrichment_results_go_singlelist.png
           :align:   center
           :scale: 60 %

           Example plot of single_set_go_enrichment()


        .. figure:: /figures/plot_enrichment_results_go_singlelist_vertical.png
           :align:   center
           :scale: 60 %

           Example plot of single_set_go_enrichment(plot_horizontal = False)
        """
        runner = enrichment_runner.GOEnrichmentRunner(self.ranked_genes, organism, gene_id_type, alpha,
                                                      propagate_annotations, aspects, evidence_types,
                                                      excluded_evidence_types, databases, excluded_databases,
                                                      qualifiers, excluded_qualifiers, return_nonsignificant, save_csv,
                                                      fname, return_fig, plot_horizontal, plot_ontology_graph,
                                                      self.set_name,
                                                      parallel=parallel, enrichment_func_name='xlmhg', single_set=True,
                                                      ontology_graph_format=ontology_graph_format)

        if gui_mode:
            return runner.run(plot=False), runner
        return runner.run()

    def single_set_kegg_enrichment(self,
                                   organism: Union[str, int, Literal['auto'], Literal[DEFAULT_ORGANISMS]] = 'auto',
                                   gene_id_type: Union[str, Literal['auto'], Literal[GENE_ID_TYPES]] = 'auto',
                                   alpha: float = 0.05, return_nonsignificant: bool = False, save_csv: bool = False,
                                   fname=None, return_fig: bool = False, plot_horizontal: bool = True,
                                   plot_pathway_graphs: bool = True, pathway_graphs_format: str = 'pdf',
                                   parallel: bool = True, gui_mode: bool = False
                                   ) -> Union[pd.DataFrame, Tuple[pd.DataFrame, plt.Figure]]:
        """
        Calculates enrichment and depletion of the sorted RankedSet for Kyoto Encyclopedia of Genes and Genomes (KEGG) \
        curated pathways WITHOUT a background set, using the generalized Minimum Hypergeometric Test \
        (XL-mHG, developed by `Prof. Zohar Yakhini and colleagues <https://dx.doi.org/10.1371/journal.pcbi.0030039/>`_ \
        and generalized by \
        `Florian Wagner <https://journals.plos.org/plosone/article?id=10.1371/journal.pone.0143196/>`_). \
        P-values are calculated using the generalized Minimum Hypergeometric Test. \
        P-values are corrected for multiple comparisons using the Benjamini–Hochberg step-up procedure \
        (original FDR method). In plots, for the clarity of display, complete depletion (linear enrichment = 0) \
        appears with the smallest value in the scale.

        :param organism: organism name or NCBI taxon ID for which the function will fetch GO annotations.
        :type organism: str or int
        :param gene_id_type: the identifier type of the genes/features in the FeatureSet object \
        (for example: 'UniProtKB', 'WormBase', 'RNACentral', 'Entrez Gene ID'). \
        If the annotations fetched from the KEGG server do not match your gene_id_type, \
        RNAlysis will attempt to map  the annotations' gene IDs to your identifier type. \
        For a full list of legal 'gene_id_type' names, see the UniProt website: \
        https://www.uniprot.org/help/api_idmapping
        :type gene_id_type: str or 'auto' (default='auto')
        :type alpha: float between 0 and 1
        :param alpha: Indicates the FDR threshold for significance.
        :type return_nonsignificant: bool (default=False)
        :type save_csv: bool, default False
        :param save_csv: If True, will save the results to a .csv file, under the name specified in 'fname'.
        :type fname: str or pathlib.Path
        :param fname: The full path and name of the file to which to save the results. For example: \
        'C:/dir/file'. No '.csv' suffix is required. If None (default), \
        fname will be requested in a manual prompt.
        :type return_fig: bool (default=False)
        :param return_fig: if True, returns a matplotlib Figure object in addition to the results DataFrame.
        :type plot_horizontal: bool (default=True)
        :param plot_horizontal: if True, results will be plotted with a horizontal bar plot. \
        Otherwise, results will be plotted with a vertical plot.
       :type plot_pathway_graphs: bool (default=True)
        :param plot_pathway_graphs: if True, will generate pathway graphs depicting the significant KEGG pathways.
        :type pathway_graphs_format: str (default='pdf')
        :param pathway_graphs_format: the file format the pathway graphs will be generated in.
        :type parallel: bool (default=True)
        :param parallel: if True, will calculate the statistical tests using parallel processing. \
        In most cases parallel processing will lead to shorter computation time, but does not affect the results of \
        the analysis otherwise.
        :rtype: pd.DataFrame (default) or Tuple[pd.DataFrame, matplotlib.figure.Figure]
        :return: a pandas DataFrame with the indicated attribute names as rows/index; \
        and a matplotlib Figure, if 'return_figure' is set to True.

        .. figure:: /figures/pathway_graph_singlelist.png
           :align:   center
           :scale: 60 %

           Example plot of single_set_kegg_enrichment(plot_pathway_graphs=True)


        .. figure:: /figures/plot_enrichment_results_kegg_single_set.png
           :align:   center
           :scale: 60 %

           Example plot of single_set_kegg_enrichment()


        .. figure:: /figures/plot_enrichment_results_kegg_single_set_vertical.png
           :align:   center
           :scale: 60 %

           Example plot of single_set_kegg_enrichment(plot_horizontal = False)
        """
        runner = enrichment_runner.KEGGEnrichmentRunner(self.ranked_genes, organism, gene_id_type, alpha,
                                                        return_nonsignificant, save_csv, fname, return_fig,
                                                        plot_horizontal, self.set_name,
                                                        parallel=parallel, enrichment_func_name='xlmhg',
                                                        single_set=True)

        if gui_mode:
            return runner.run(plot=False), runner
        return runner.run()

    def single_set_enrichment(self, attributes: Union[List[str], str, List[int], int, Literal['all']],
                              alpha: float = 0.05,
                              attr_ref_path: Union[str, Path, Literal['predefined']] = 'predefined',
                              return_nonsignificant: bool = True,
                              save_csv: bool = False, fname=None, return_fig: bool = False,
                              plot_horizontal: bool = True, parallel: bool = True, gui_mode: bool = False):
        """
        Calculates enrichment and depletion of the sorted RankedSet for user-defined attributes \
        WITHOUT a background set, using the generalized Minimum Hypergeometric Test (XL-mHG, developed by  \
        `Prof. Zohar Yakhini and colleagues <https://dx.doi.org/10.1371/journal.pcbi.0030039/>`_ \
        and generalized by \
        `Florian Wagner <https://journals.plos.org/plosone/article?id=10.1371/journal.pone.0143196/>`_). \
        The attributes are drawn from an Attribute Reference Table. \
        P-values are calculated using using the generalized Minimum Hypergeometric Test. \
        P-values are corrected for multiple comparisons using the Benjamini–Hochberg step-up procedure \
        (original FDR method). In plots, for the clarity of display, complete depletion (linear enrichment = 0) \
        appears with the smallest value in the scale.

        :type attributes: str, int, iterable (list, tuple, set, etc) of str/int, or 'all'.
        :param attributes: An iterable of attribute names or attribute numbers \
        (according to their order in the Attribute Reference Table). \
        If 'all', all of the attributes in the Attribute Reference Table will be used. \
        If None, a manual input prompt will be raised.
        :type alpha: float between 0 and 1
        :param alpha: Indicates the FDR threshold for significance.
        :type attr_ref_path: str or pathlib.Path (default='predefined')
        :param attr_ref_path: path of the Attribute Reference Table from which user-defined attributes will be drawn.
        :param return_nonsignificant: if True (default), the results DataFrame will include all tested attributes - \
        both significant and non-significant ones. If False, only significant attributes will be returned.
        :type return_nonsignificant: bool (default=True)
        :type save_csv: bool, default False
        :param save_csv: If True, will save the results to a .csv file, under the name specified in 'fname'.
        :type fname: str or pathlib.Path
        :param fname: The full path and name of the file to which to save the results. For example: \
        'C:/dir/file'. No '.csv' suffix is required. If None (default), fname will be requested in a manual prompt.
        :type return_fig: bool (default=False)
        :param return_fig: if True, returns a matplotlib Figure object in addition to the results DataFrame.
        :type plot_horizontal: bool (default=True)
        :param plot_horizontal: if True, results will be plotted with a horizontal bar plot. Otherwise, results \
        will be plotted with a vertical plot.
        :type parallel: bool (default=True)
        :param parallel: if True, will calculate the statistical tests using parallel processing. \
        In most cases parallel processing will lead to shorter computation time, but does not affect the results of \
        the analysis otherwise.
        :rtype: pd.DataFrame (default) or Tuple[pd.DataFrame, matplotlib.figure.Figure]
        :return: a pandas DataFrame with the indicated attribute names as rows/index; \
        and a matplotlib Figure, if 'return_figure' is set to True.

        .. figure:: /figures/plot_enrichment_results_single_set.png
           :align:   center
           :scale: 60 %

           Example plot of single_set_enrichment()


        .. figure:: /figures/plot_enrichment_results_single_set_vertical.png
           :align:   center
           :scale: 60 %

           Example plot of single_set_enrichment(plot_horizontal = False)

        """
        runner = enrichment_runner.EnrichmentRunner(self.ranked_genes, attributes, alpha, attr_ref_path,
                                                    return_nonsignificant, save_csv,
                                                    fname, return_fig, plot_horizontal, self.set_name,
                                                    parallel=parallel, enrichment_func_name='xlmhg', single_set=True)
        if gui_mode:
            return runner.run(plot=False), runner
        return runner.run()


def plot_enrichment_results(results_df: pd.DataFrame, alpha=0.05, en_score_col: str = 'log2_fold_enrichment',
                            name_col: str = None, title: str = '', center_bars: bool = True,
                            plot_horizontal: bool = True, ylabel: str = r"$\log_2$(Fold Enrichment)") -> plt.Figure:
    """
    Receives a DataFrame output from an enrichment function and plots it in a bar plot. \
    For the clarity of display, complete depletion (linear enrichment = 0) \
    appears with the smallest value in the scale.

    :param results_df: the results DataFrame returned by enrichment functions.
    :type results_df: pandas DataFrame
    :param alpha: the threshold for statistical significance. Used to draw significance asterisks on the graph.
    :type alpha: float (default=0.05)
    :param en_score_col: name of the DataFrame column containing enrichment scores.
    :type en_score_col: str (default='log2_fold_enrichment')
    :param name_col: name of the DataFrame column containing attribute/GO term names.
    :type name_col: str (default=None)
    :param results_df: a pandas DataFrame created by FeatureSet.enrich_randomization.
    :type results_df: pd.DataFrame
    :param en_score_col: name of the DataFrame column that contains the enrichment scores.
    :type en_score_col: str (default='log2_fold_enrichment')
    :param title: plot title.
    :type title: str
    :param plot_horizontal: if True, results will be plotted with a horizontal bar plot. \
        Otherwise, results will be plotted with a vertical plot.
    :type plot_horizontal: bool (default=True)
    :param ylabel: plot ylabel.
    :type ylabel: str (default=r"$\log_2$(Fold Enrichment)")
    :param center_bars: if True, center the bars around Y=0. Otherwise, ylim is determined by min/max values.
    :type center_bars: bool (default=True)
    :return: Figure object containing the bar plot
    :rtype: matplotlib.figure.Figure instance
    """
    runner = enrichment_runner.EnrichmentRunner(set(), results_df.index, alpha, '', True, False, '', True,
                                                plot_horizontal, '', False, 'hypergeometric', 'all')
    runner.en_score_col = en_score_col
    runner.results = results_df
    return runner.enrichment_bar_plot(name_col=name_col, center_bars=center_bars, ylabel=ylabel, title=title)


def _fetch_sets(objs: dict, ref: Union[str, Path, Literal['predefined']] = 'predefined'):
    """
    Receives the 'objs' input from enrichment.upset_plot() and enrichment.venn_diagram(), and turns the values in it \
    into python sets.

    :param objs: the 'objs' input given to the function enrichment.upset_plot() or enrichment.venn_diagram().
    :type objs: a dictionary, where the keys are names of sets, and the values are either\
     python sets, FeatureSets or names of columns in the Attribute Reference Table.
    :param ref: the path of the Attribute Reference Table from which user-defined attributes will be drawn, \
    if such attributes are included in 'objs'.
    :type ref: str or pathlib.Path (default='predefined')
    :return: a dictionary, where the keys are names of sets and the values are python sets of feature indices.
    """
    assert isinstance(objs, dict), f"objs must be a dictionary. Instaed got {type(objs)}"
    fetched_sets = dict()

    if validation.isinstanceiter_any(objs.values(), str):
        attr_ref_table = io.load_csv(settings.get_attr_ref_path(ref))
        validation.validate_attr_table(attr_ref_table)
        attr_ref_table.set_index('gene', inplace=True)

    for set_name, set_obj in zip(objs.keys(), objs.values()):
        if isinstance(objs[set_name], (set, list, tuple)):
            fetched_sets[set_name] = parsing.data_to_set(set_obj)
        elif validation.isinstanceinh(set_obj, Filter):
            fetched_sets[set_name] = set_obj.index_set
        elif validation.isinstanceinh(set_obj, FeatureSet):
            fetched_sets[set_name] = set_obj.gene_set
        elif isinstance(set_obj, str):
            fetched_sets[set_name] = set(attr_ref_table[set_obj].loc[attr_ref_table[set_obj].notna()].index)
        else:
            raise TypeError(f"Invalid type for the set '{set_name}': {set_obj}.")

    return fetched_sets


def upset_plot(objs: Dict[str, Union[str, FeatureSet, Set[str]]], set_colors: Iterable[str] = ('black',),
               title: str = 'UpSet Plot', title_fontsize: int = 20, show_percentages: bool = True,
               attr_ref_table_path: Union[str, Path, Literal['predefined']] = 'predefined', fig: plt.Figure = None):
    """
    Generate an UpSet plot of 2 or more sets, FeatureSets or attributes from the Attribute Reference Table.

    :param objs: the FeatureSets, python sets or user-defined attributes to plot.
    :type objs: a dictionary with 2 or more entries, where the keys are the names of the sets, and the values are either \
    a FeatureSet, a python set of feature indices, or a name of a column in the Attribute Reference Table. \
    For example: \
    {'first set':{'gene1','gene2','gene3'}, 'second set':'name_of_attribute_from_reference_table'}
    :param set_colors: I\if one color is supplied, this will determine the color of all sets on the plot. \
    If multiple colors are supplied, this will determine the color of each set on the plot, and the subset colors \
    will be determined by mixing.
    :type set_colors: Iterable of colors (default=('black',)
    :param title: determines the title of the plot.
    :type title: str
    :param title_fontsize: font size for the plot's title
    :type title_fontsize: int (default=20)
    :param show_percentages: if True, shows the percentage that each set or subset takes out of the entire dataset.
    :type show_percentages: bool (default=True)
    :param attr_ref_table_path: the path of the Attribute Reference Table from which user-defined attributes will be drawn, \
    if such attributes are included in 'objs'.
    :type attr_ref_table_path: str or pathlib.Path (default='predefined')
    :param fig: optionally, supply your own Figure to generate the plot onto.
    :type fig: matplotlib.Figure

    :returns: a dictionary of matplotlib axes, where the keys are 'matrix', 'intersections', 'totals', 'shading'.


        .. figure:: /figures/upsetplot.png
           :align:   center
           :scale: 70 %

           Example plot of upset_plot()
    """

    upset_df = parsing.generate_upset_series(_fetch_sets(objs=objs, ref=attr_ref_table_path))
    upset_obj = upsetplot.UpSet(upset_df, sort_by='degree', sort_categories_by=None, show_percentages=show_percentages)
    axes = upset_obj.plot(fig=fig)
    if fig is None:
        fig = plt.gcf()

    set_colors = [matplotlib.colors.to_rgb(color) for color in parsing.data_to_list(set_colors)]
    if len(set_colors) == 1:
        set_colors = [set_colors[0]] * len(objs)
    elif len(set_colors) > len(objs):
        set_colors = set_colors[0:len(objs)]
    elif len(set_colors) < len(objs):
        set_colors = set_colors + [(0, 0, 0)] * (len(objs) - len(set_colors))

    for main_set in range(len(objs)):
        color = set_colors[main_set]
        axes['totals'].patches[main_set].set_facecolor(color)

    patcn_ids = _get_tuple_patch_ids(len(objs))
    for subset in range(len(upset_obj.subset_styles)):
        id = patcn_ids[subset]
        colors_to_mix = [set_colors[ind] for ind, is_present in enumerate(id) if is_present]
        color = generic.mix_colors(*colors_to_mix)
        upset_obj.subset_styles[subset]['facecolor'] = color
        axes['intersections'].patches[subset].set_facecolor(color)
    matrix_ax = axes['matrix']
    matrix_ax.clear()
    upset_obj.plot_matrix(matrix_ax)
    fig.suptitle(title, fontsize=title_fontsize)
    return upset_obj


def _compare_ids(id1: Tuple[int, ...], id2: Tuple[int, ...]):
    if sum(id1) > sum(id2):
        return 1
    elif sum(id1) < sum(id2):
        return -1
    else:
        for i in range(len(id1), 0, -1):
            ind = i - 1
            if id1[ind] > id2[ind]:
                return 1
            elif id1[ind] < id2[ind]:
                return -1
        return 0


def _get_tuple_patch_ids(n_sets: int) -> List[Tuple[int, ...]]:
    unsorted_ids = list(itertools.product([0, 1], repeat=n_sets))[1:]
    sorted_ids = sorted(unsorted_ids, key=functools.cmp_to_key(_compare_ids))
    return sorted_ids


def venn_diagram(objs: Dict[str, Union[str, FeatureSet, Set[str]]], title: Union[str, Literal['default']] = 'default',
                 attr_ref_table_path: Union[str, Path, Literal['predefined']] = 'predefined',
                 set_colors: Iterable[str] = ('r', 'g', 'b'),
                 transparency: float = 0.4, weighted: bool = True, add_outline: bool = True, linecolor: str = 'black',
                 linestyle: Literal['solid', 'dashed'] = 'solid', linewidth: float = 2.0, title_fontsize: int = 14,
                 set_fontsize: int = 12, subset_fontsize: int = 10, normalize_to: float = 1.0, fig: plt.Figure = None):
    """
    Generate a Venn diagram of 2 to 3 sets, FeatureSets or attributes from the Attribute Reference Table.

    :param objs: the FeatureSets, python sets or user-defined attributes to plot.
    :type objs: a dictionary with 2-3 entries, where the keys are the names of the sets, and the values are either \
    a FeatureSet, a python set of feature indices, or a name of a column in the Attribute Reference Table. \
    For example: \
    {'first set':{'gene1','gene2','gene3'}, 'second set':'name_of_attribute_from_reference_table'}
    :type title: str or 'default' (default='default')
    :param set_colors: determines the colors of the circles in the diagram.
    :param attr_ref_table_path: the path of the Attribute Reference Table from which user-defined attributes will be drawn, \
    if such attributes are included in 'objs'.
    :type attr_ref_table_path: str or pathlib.Path (default='predefined')
    :param title: determines the title of the plot.
    :type set_colors: tuple of matplotlib-format colors, the same size as 'objs'
    :param transparency: determines the opacity of the circles. \
    Opacity of 0 is completely transparent, while opacity of 1 is completely opaque.
    :type transparency: a float between 0 and 1
    :param weighted: if True, the plot will be area-weighted.
    :type weighted: bool (default=True)
    :param add_outline: if True, adds an outline to the circles.
    :type add_outline: bool (default=True)
    :param linecolor: Determines the color of the circles' outline.
    :type linecolor: matplotlib-format color (default='black')
    :param linestyle: the style of the circles' outline.
    :type linestyle: 'solid' or 'dashed' (default='solid')
    :param linewidth: the widdth of the circles' outlines.
    :type linewidth: float (default=2.0)
    :param title_fontsize: font size for the plot's title.
    :type title_fontsize: int (default=14)
    :param set_fontsize: font size for the set labels.
    :type set_fontsize: int (default=12)
    :param subset_fontsize: font size for the subset labels.
    :type subset_fontsize: int (default=10)
    :param fig: optionally, supply your own Figure to generate the plot onto.
    :type fig: matplotlib.Figure

    :param normalize_to: the total (on-axes) area of the circles to be drawn. Sometimes tuning it (together
    with the overall fiture size) may be useful to fit the text labels better.
    :type normalize_to: float (default=1.0)
    :return: a tuple of a VennDiagram object; and a list of 2-3 Circle patches.


        .. figure:: /figures/venn.png
           :align:   center
           :scale: 70 %

           Example plot of venn_diagram()
    """
    if len(objs) > 3 or len(objs) < 2:
        raise ValueError(f'Venn can only accept between 2 and 3 sets. Instead got {len(objs)}')
    assert isinstance(title, str), f'Title must be a string. Instead got {type(title)}'
    objs = _fetch_sets(objs=objs, ref=attr_ref_table_path)
    set_colors = parsing.data_to_tuple(set_colors)
    if len(set_colors) == 1:
        set_colors *= 3

    if len(objs) == 2:
        func = vn.venn2 if weighted else vn.venn2_unweighted
        func_circles = vn.venn2_circles
        set_colors = set_colors[0:2]
    else:
        func = vn.venn3 if weighted else vn.venn3_unweighted
        func_circles = vn.venn3_circles
        set_colors = set_colors[0:3]
    if fig is None:
        fig = plt.figure()
    ax = fig.add_subplot()
    plot_obj = func(tuple(objs.values()), tuple(objs.keys()), set_colors=set_colors, alpha=transparency,
                    normalize_to=normalize_to, ax=ax)
    if add_outline and weighted:
        circle_obj = func_circles(tuple(objs.values()), color=linecolor, linestyle=linestyle, linewidth=linewidth,
                                  normalize_to=normalize_to, ax=ax)
    elif add_outline and not weighted:
        circle_obj = func(tuple(objs.values()), tuple(objs.keys()), alpha=1, normalize_to=normalize_to, ax=ax)
        for patch in circle_obj.patches:
            patch.set_edgecolor(linecolor)
            patch.set_linewidth(linewidth)
            patch.set_linestyle(linestyle)
            patch.set_fill(False)
    else:
        circle_obj = None

    for label in plot_obj.set_labels:
        label.set_fontsize(set_fontsize)
    for sublabel in plot_obj.subset_labels:
        if sublabel is not None:
            sublabel.set_fontsize(subset_fontsize)

    if title == 'default':
        title = 'Venn diagram of ' + ''.join([name + ' ' for name in objs.keys()])
    ax.set_title(title, fontsize=title_fontsize)
    return plot_obj, circle_obj
